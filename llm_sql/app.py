"""
업로드 데이터 챗봇의 AI+SQL 로직 모듈.

컬럼이 매번 달라지는 파일을 처리하기 위해 스키마를 하드코딩하지 않고
파일이 로드된 DuckDB 뷰에서 동적으로 읽는다.

제공 함수:
- get_duckdb_connection(): DuckDB 커넥션 생성
- load_into_duckdb(con, file): CSV/Parquet 파일을 uploaded_data 뷰로 등록
- connect_latest_parquet(con, url): backend 서버의 최신 parquet을 뷰로 연결
- upload_file_in_chunks(file_path, url): 대용량 파일을 청크 업로드
- get_schema(con): 현재 uploaded_data 뷰의 컬럼 목록과 타입을 반환
- answer_question(con, question): 자연어 → SQL 생성 → 검증 → 실행 → 요약
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

import requests
from dotenv import load_dotenv

import duckdb
import polars as pl
from anthropic import Anthropic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

# =====================================
# Claude API 설정
# =====================================

api_key = os.environ.get("ANTHROPIC_API_KEY")

if not api_key:
    raise RuntimeError(
        "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
        "프로젝트 최상위 폴더의 .env 파일에 키를 넣어주세요."
    )

client = Anthropic(api_key=api_key)
CLAUDE_MODEL = "claude-sonnet-5"

# =====================================
# DuckDB 연결
# =====================================

def get_duckdb_connection():
    """이 모듈 전용 DuckDB 커넥션을 새로 만든다."""
    return duckdb.connect()


def load_into_duckdb(con, file) -> int:
    """
    CSV 또는 Parquet 파일(경로 문자열 또는 파일 객체)을
    uploaded_data 뷰로 등록한다. 반환값은 로드된 행 수.
    """
    if isinstance(file, (str, os.PathLike)):
        path = str(file)
        if path.lower().endswith(".parquet"):
            con.execute(f"""
                CREATE OR REPLACE VIEW uploaded_data AS
                SELECT * FROM read_parquet('{path}')
            """)
        else:
            con.execute(f"""
                CREATE OR REPLACE VIEW uploaded_data AS
                SELECT * FROM read_csv_auto('{path}')
            """)
    else:
        # Streamlit UploadedFile 등 파일 객체인 경우
        data = pl.read_csv(file)
        con.register("_uploaded_data", data)
        con.execute("""
            CREATE OR REPLACE VIEW uploaded_data AS
            SELECT * FROM _uploaded_data
        """)

    row_count = con.execute("SELECT COUNT(*) FROM uploaded_data").fetchone()[0]
    return row_count


def connect_latest_parquet(con, upload_server_url: str = "http://127.0.0.1:8000") -> str:
    """
    backend/upload_server.py 에 최근 업로드된 parquet 파일을
    uploaded_data 뷰로 연결한다. 연결한 parquet 파일 경로를 반환한다.
    """
    response = requests.get(f"{upload_server_url}/upload/latest", timeout=3)
    response.raise_for_status()
    file_path = response.json()["file_path"]

    con.execute(f"""
        CREATE OR REPLACE VIEW uploaded_data AS
        SELECT * FROM read_parquet('{file_path}')
    """)
    return file_path


def upload_file_in_chunks(file_path, upload_server_url="http://127.0.0.1:8000"):
    """
    대용량 파일을 backend/upload_server.py 로 청크 업로드한다.
    Streamlit 컨텍스트 밖에서도 호출할 수 있도록 st 를 함수 안에서만 import한다.
    """
    import streamlit as st

    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    init_resp = requests.post(
        f"{upload_server_url}/upload/init",
        data={"filename": filename, "file_size": file_size},
        timeout=30,
    )
    init_resp.raise_for_status()
    info = init_resp.json()
    upload_id = info["upload_id"]
    chunk_size = info["chunk_size"]
    total_chunks = info["total_chunks"]

    progress_bar = st.progress(0)
    status_text = st.empty()

    with open(file_path, "rb") as f:
        for idx in range(total_chunks):
            chunk_data = f.read(chunk_size)
            resp = requests.post(
                f"{upload_server_url}/upload/chunk",
                data={"upload_id": upload_id, "chunk_index": idx},
                files={"chunk": (f"chunk_{idx}", chunk_data)},
                timeout=300,
            )
            resp.raise_for_status()
            progress_bar.progress((idx + 1) / total_chunks)
            status_text.text(f"업로드 중... {idx + 1}/{total_chunks} 청크 완료")

    complete_resp = requests.post(
        f"{upload_server_url}/upload/complete",
        data={"upload_id": upload_id, "filename": filename, "total_chunks": total_chunks},
        timeout=300,
    )
    complete_resp.raise_for_status()
    progress_bar.progress(1.0)
    status_text.success("대용량 파일 업로드 완료!")
    return complete_resp.json()["file_path"]


# =====================================
# 동적 스키마 읽기
# =====================================

def get_schema(con) -> tuple[str, set[str]]:
    """
    현재 uploaded_data 뷰의 컬럼 정보를 DuckDB에서 동적으로 읽는다.

    반환:
        schema_str   — Claude 프롬프트에 넣을 스키마 설명 문자열
        allowed_cols — validate_sql 에 사용할 허용 컬럼 집합 (소문자)
    """
    rows = con.execute("DESCRIBE uploaded_data").fetchall()
    # rows: [(column_name, column_type, null, key, default, extra), ...]

    schema_lines = ["테이블명: uploaded_data\n", "컬럼 목록:"]
    allowed_cols: set[str] = set()

    for row in rows:
        col_name = row[0]
        col_type = row[1]
        schema_lines.append(f"  - {col_name}  ({col_type})")
        allowed_cols.add(col_name.lower())

    schema_str = "\n".join(schema_lines)
    return schema_str, allowed_cols


# =====================================
# SQL 검증 (동적 컬럼 기반)
# =====================================

ALLOWED_TABLE = "uploaded_data"

SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "ASC", "DESC",
    "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IN", "IS", "NULL",
    "BETWEEN", "LIKE", "CASE", "WHEN", "THEN", "ELSE", "END",
    "DISTINCT", "HAVING", "OVER", "PARTITION", "ROW_NUMBER", "RANK",
    "DENSE_RANK", "TRUE", "FALSE", "MESSAGE",
}

SQL_FUNCTIONS = {
    "COUNT", "AVG", "SUM", "MAX", "MIN",
    "ROUND", "COALESCE", "CAST", "NULLIF", "IFNULL",
    "STRFTIME", "DATE", "YEAR", "MONTH", "DAY", "DATE_PART",
    "UPPER", "LOWER", "TRIM", "LENGTH",
    "SUBSTR", "CONCAT", "REPLACE", "POSITION",
    "STDDEV", "VARIANCE", "MEDIAN",
    "ABS", "POWER", "SQRT", "GREATEST", "LEAST",
}

SQL_TYPES = {
    "INTEGER", "BIGINT", "DOUBLE", "FLOAT", "VARCHAR",
    "TEXT", "DECIMAL", "BOOLEAN", "DATE", "TIMESTAMP",
}

FORBIDDEN_KEYWORDS = {
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
    "CREATE", "TRUNCATE", "ATTACH", "DETACH",
    "COPY", "EXPORT", "IMPORT",
}


def validate_sql(sql: str, allowed_cols: set[str]) -> tuple[bool, str]:
    """
    생성된 SQL을 실행 전에 검증한다.
    allowed_cols 는 get_schema()에서 동적으로 읽은 컬럼 집합(소문자).
    """
    if not sql or not sql.strip():
        return False, "SQL이 생성되지 않았습니다."

    sql = sql.strip()
    sql_upper = sql.upper()

    # 여러 문장 차단
    if ";" in sql.rstrip(";"):
        return False, "여러 SQL 문장은 실행할 수 없습니다."

    # SELECT만 허용
    if not re.match(r"^\s*SELECT\b", sql_upper):
        return False, "SELECT 문만 사용할 수 있습니다."

    # 위험 명령 차단
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", sql_upper):
            return False, f"{kw} 명령은 사용할 수 없습니다."

    # 문자열 리터럴 제거 후 검사
    sql_for_check = re.sub(r"'(?:[^']|'')*'", "''", sql)

    # 테이블 검사
    tables = re.findall(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        sql_for_check,
        re.IGNORECASE,
    )
    for table in tables:
        if table.lower() != ALLOWED_TABLE:
            return False, f"허용되지 않은 테이블입니다: {table}"

    # 큰따옴표로 감싼 식별자(공백/특수문자가 있는 컬럼명, 예: "Unnamed: 0")는
    # 통째로 하나의 토큰으로 검사한다. 그렇지 않으면 아래 단어 단위
    # 토큰화가 따옴표 안 일부만 뽑아내(예: "Unnamed") 실제로는 허용된
    # 컬럼을 존재하지 않는 컬럼으로 오인해 차단하게 된다.
    quoted_identifiers = re.findall(r'"([^"]+)"', sql_for_check)
    for identifier in quoted_identifiers:
        if identifier.lower() not in allowed_cols:
            return False, f"허용되지 않은 컬럼 또는 식별자입니다: {identifier}"
    sql_without_quoted = re.sub(r'"[^"]+"', " ", sql_for_check)

    # 컬럼 검사 — 동적 화이트리스트
    aliases = {
        a.upper()
        for a in re.findall(
            r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_without_quoted, re.IGNORECASE
        )
    }
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", sql_without_quoted)

    for token in tokens:
        token_upper = token.upper()
        if token_upper in aliases:
            continue
        if token_upper in SQL_KEYWORDS:
            continue
        if token_upper in SQL_FUNCTIONS:
            continue
        if token_upper in SQL_TYPES:
            continue
        if token.lower() == ALLOWED_TABLE:
            continue
        if token.lower() in allowed_cols:
            continue
        return False, f"허용되지 않은 컬럼 또는 식별자입니다: {token}"

    return True, ""


# =====================================
# 결과 행수 상한
# =====================================

MAX_RESULT_ROWS = 5000

# LIMIT을 붙일 때 실제 전체 매칭 행수를 함께 실어 보내기 위한 임시 컬럼명.
# 실제 데이터 컬럼과 겹치지 않도록 이중 밑줄을 앞뒤로 붙인다.
TOTAL_COUNT_COL = "__row_limit_total__"


def _apply_row_limit(sql: str, max_rows: int = MAX_RESULT_ROWS) -> tuple[str, bool]:
    """
    수십 GB 규모 데이터에서 LIMIT 없는 쿼리가 결과를 통째로 끌고 오지
    않도록 상한을 강제한다. 이미 LIMIT이 있으면 그대로 둔다.

    상한을 새로 적용할 때는 COUNT(*) OVER() 창 함수로 LIMIT 적용 전
    전체 행수(TOTAL_COUNT_COL)를 같이 실어 보낸다. 그래야 나열형 쿼리가
    잘리더라도 "실제로 몇 건이 조건에 맞았는지"를 잃어버리지 않는다.

    반환: (실행할 SQL, 상한을 새로 적용했는지 여부)
    """
    s = sql.strip().rstrip(";").strip()
    if re.search(r"\bLIMIT\s+\d+\b", s, re.IGNORECASE):
        return s, False

    wrapped = (
        f"SELECT *, COUNT(*) OVER() AS {TOTAL_COUNT_COL} "
        f"FROM ({s}) AS __row_limit_subquery "
        f"LIMIT {max_rows}"
    )
    return wrapped, True


# =====================================
# SQL 생성 (Claude API)
# =====================================

def _extract_text(response) -> str:
    """
    Claude 응답에서 실제 텍스트 블록을 찾아 반환한다.

    확장 사고(thinking)를 사용하는 모델은 response.content[0]이 텍스트가
    아니라 ThinkingBlock일 수 있어서, 항상 첫 블록이 텍스트라고 가정하면
    안 된다. content 배열을 순회해 type이 "text"인 블록을 찾는다.
    """
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise RuntimeError("Claude 응답에서 텍스트 블록을 찾지 못했습니다.")


def _build_spec_section(spec_text: str) -> str:
    """
    확정된 질의 명세를 프롬프트 섹션으로 만든다.
    명세가 없으면 빈 문자열이라 섹션 자체가 프롬프트에 생기지 않는다.
    """
    if not spec_text:
        return ""

    return f"""
==================================================
확정된 질의 명세 (사용자가 직접 확인해 준 기준)
==================================================

아래는 과거에 기준이 모호해서 사용자에게 되물었을 때, 사용자가 직접
알려준 해석 기준이다. 이번 질문이 아래 항목과 같은 표현을 쓰고 있다면
모호하다고 판단하지 말고, 명시된 기준을 그대로 적용해 정상적인 SELECT
문을 만든다.

{spec_text}
"""


def _build_sql_prompt(question: str, schema: str, spec_text: str = "") -> str:
    return f"""
너는 데이터 분석용 SQL 생성기다.

아래는 현재 업로드된 파일의 실제 스키마다:

{schema}

사용자 질문:
{question}
{_build_spec_section(spec_text)}

==================================================
규칙
==================================================

1. 위 스키마에 존재하는 컬럼만 사용한다. 컬럼명 대소문자는 스키마에 적힌
   그대로 정확히 맞춰 쓴다("price"가 아니라 스키마에 있는 대로 "PRICE").
2. 테이블명은 반드시 uploaded_data 만 사용한다. 조회 대상이 이 테이블
   하나뿐이므로 테이블에 별칭(alias)을 붙이지 않는다 (예:
   "FROM uploaded_data nh"나 "FROM uploaded_data AS nh"처럼 쓰지 말고
   항상 "FROM uploaded_data"라고만 쓴다). 컬럼을 쓸 때도
   "uploaded_data.컬럼"이 아니라 컬럼명만 그대로 쓴다.
2-1. 컬럼명에 공백이나 특수문자, 콜론 등이 포함되어 있으면(예: "Unnamed: 0")
   반드시 큰따옴표로 감싸서 쓴다(예: "Unnamed: 0"). 큰따옴표 없이 그대로
   쓰면 SQL 문법 오류가 난다.
3. SELECT 문 하나만 만든다.
4. DROP, DELETE, UPDATE, INSERT, ALTER, CREATE 등은 절대 사용하지 않는다.
5. 질문에 없는 조건을 임의로 추가하지 않는다.
6. 다음 함수만 사용할 수 있다: COUNT, AVG, SUM, MAX, MIN, ROUND, COALESCE,
   CAST, NULLIF, IFNULL, STRFTIME, DATE, YEAR, MONTH, DAY, DATE_PART,
   UPPER, LOWER, TRIM, LENGTH, SUBSTR, CONCAT, REPLACE, POSITION,
   STDDEV, VARIANCE, MEDIAN, ABS, POWER, SQRT, GREATEST, LEAST.
   이 목록에 없는 함수는 사용하지 않는다.
7. 날짜에서 일부를 뽑을 때는 EXTRACT(... FROM ...) 대신
   DATE_PART('year', 컬럼) 형태의 함수 호출 문법을 사용한다.
8. 결과 컬럼에 별칭(AS)을 붙일 때는 원본 컬럼명 대신 의미가 드러나는
   이름을 쓴다 (예: COUNT(*) AS cnt).

조건 표현:
  "이상" → >=   "초과" → >   "이하" → <=   "미만" → <

집계 표현:
  "몇 개" / "개수" → COUNT(*)
  "평균" → AVG()   "합계" → SUM()
  "최댓값" → MAX()  "최솟값" → MIN()

그룹 표현:
  "~별" → GROUP BY 해당 컬럼

정렬 표현:
  "많은 순" / "높은 순" → ORDER BY DESC
  "적은 순" / "낮은 순" → ORDER BY ASC

도구 사용법/대화성 질문 (데이터 조회가 아니라 이 챗봇 자체에 대해 묻거나
가벼운 대화를 거는 경우 — 예: "이 기능 어떻게 써", "명세서가 뭐야",
"고마워", "잘 작동하는 거 맞아?"):
  데이터를 조회할 필요가 없다. 아래 참고 정보를 바탕으로 질문에 바로
  답하는 message SQL을 만든다. 데이터 질문이 아니므로 ambiguous 필드는
  반드시 null로 둔다.

  참고: 이 챗봇의 동작 방식
  - 자연어 질문을 SQL로 변환해 업로드된 데이터를 조회한다.
  - 조회 기준이 모호한 질문(예: "불량인 것만 보여줘")에는 바로 답하지
    않고 구체적인 기준을 되묻는다. 사용자가 기준을 알려주면 그 내용이
    "질의 명세서"(화면 오른쪽 패널)에 저장되고, 이후 같은 표현이 나오면
    되묻지 않고 그 기준을 바로 적용한다.
  - 즉 명세서 기능을 써보려면, 기준이 애매한 질문을 던져서 되물음을
    받은 뒤 구체적인 기준으로 답하면 된다.

  SELECT '<질문에 대한 안내 답변>' AS message;

스키마/컬럼 목록 질문 ("어떤 컬럼이 있어", "칼럼 알려줘", "스키마 보여줘"처럼
데이터 구조 자체를 묻는 경우):
  이 데이터가 실제로 가진 컬럼과 타입은 이미 위 스키마에 나와 있으므로
  information_schema 등 다른 테이블을 조회할 필요가 없다. 그 목록을 사람이
  읽기 좋은 한 문장으로 정리해서 아래처럼 message로 반환한다.

  SELECT '이 데이터는 다음 컬럼을 가지고 있습니다: <컬럼명(타입), 컬럼명(타입), ...>' AS message;

  이건 모호한 질문이 아니라 정상적으로 답할 수 있는 질문이므로 ambiguous
  필드는 반드시 null로 둔다.

모호한 질문 (구체적 수치 기준 없이 "고장", "불량", "위험" 등만 있는 경우):
  위에 "확정된 질의 명세" 섹션이 있고 거기에 해당 표현의 기준이 적혀 있다면
  모호한 것으로 보지 않고 그 기준을 그대로 적용한다. 참고할 기준이 없어
  정말로 판단할 수 없을 때만 아래 SQL을 만들고, 출력 형식의 ambiguous
  필드도 함께 채운다.

  SELECT '질문의 기준이 명확하지 않습니다.' AS message;

==================================================
차트 힌트
==================================================

SQL 결과를 함께 시각화할 수 있는지 판단해서 chart 정보도 만든다.

- 결과가 "카테고리별 집계"처럼 x축(범주/시간)과 y축(숫자) 조합으로
  의미가 있으면 chart를 채운다. type은 다음 중 하나:
    "bar"  — 카테고리별 비교
    "line" — 시간/순서에 따른 추이
    "pie"  — 전체 대비 비율 (카테고리 5개 이하일 때만)
- x, y 값은 반드시 SELECT 절에 실제로 나오는 컬럼명(또는 AS 별칭)과
  정확히 같은 문자열이어야 한다.
- 단일 값 하나만 반환되는 쿼리, 메시지만 반환하는 쿼리, 또는 의미 있는
  x/y 조합이 없는 쿼리는 chart를 null로 둔다.

==================================================
출력 형식
==================================================

아래 형식의 JSON 객체 하나만 출력한다. 그 외 어떤 텍스트, 설명,
마크다운 코드 블록도 포함하지 않는다.

{{"sql": "<SELECT 문>", "chart": {{"type": "bar", "x": "<컬럼명>", "y": "<컬럼명>"}} 또는 null, "ambiguous": {{"reason": "<무엇이 모호한지 한 문장>", "ask": "<사용자에게 되물을 한 문장>"}} 또는 null}}

ambiguous 는 위 "모호한 질문"에 해당할 때만 채우고, 정상적인 SQL을
만들었을 때는 반드시 null 로 둔다. ask 에는 사용자가 무엇을 알려주면
답할 수 있는지를 구체적으로 적는다 (예: "어떤 컬럼이 몇 이상일 때를
불량으로 볼지 알려주세요").
"""


def generate_sql_and_chart(question: str, schema: str, spec_text: str = "") -> dict:
    """
    자연어 질문을 uploaded_data 테이블에 대한 SELECT SQL 문과 차트 힌트로 변환한다.

    spec_text: 확정된 질의 명세(spec_store.format_specs_for_prompt 결과).
               넘기면 모호한 표현이라도 명세에 기준이 있으면 그대로 답한다.

    반환: {"sql": str, "chart": dict | None, "ambiguous": dict | None}
          ambiguous 는 기준이 모호해 답을 보류할 때만 채워지며
          {"reason": str, "ask": str} 형태다.
    """
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=(
            "너는 정확한 SQL과 시각화 힌트를 생성하는 데이터 분석 전문가다. "
            "반드시 순수 JSON 객체 하나만 출력한다."
        ),
        messages=[
            {"role": "user", "content": _build_sql_prompt(question, schema, spec_text)}
        ],
    )
    raw = _extract_text(response).strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # JSON 파싱에 실패하면 통짜 텍스트를 SQL로 간주하고 차트는 포기한다.
        return {"sql": raw, "chart": None, "ambiguous": None}

    sql = str(parsed.get("sql", "")).strip()
    chart = parsed.get("chart")
    if not isinstance(chart, dict):
        chart = None

    ambiguous = parsed.get("ambiguous")
    if isinstance(ambiguous, dict):
        ambiguous = {
            "reason": str(ambiguous.get("reason", "")).strip(),
            "ask": str(ambiguous.get("ask", "")).strip(),
        }
    else:
        ambiguous = None

    return {"sql": sql, "chart": chart, "ambiguous": ambiguous}


# =====================================
# 추천 질문 생성 (Claude API)
# =====================================

def _fallback_questions(con, count: int) -> list[str]:
    """
    Claude 호출이 실패했을 때 쓰는 대비책. 어떤 파일이든 컬럼 이름만
    알면 만들 수 있는 질문이라 특정 도메인에 의존하지 않는다.
    """
    try:
        rows = con.execute("DESCRIBE uploaded_data").fetchall()
    except Exception:
        return []

    numeric_types = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "BIGINT")
    text_cols = [r[0] for r in rows if not any(t in r[1].upper() for t in numeric_types)]
    num_cols = [r[0] for r in rows if any(t in r[1].upper() for t in numeric_types)]

    questions = ["전체 데이터가 몇 건이야?"]
    if text_cols:
        questions.append(f"{text_cols[0]}별 개수를 보여줘")
    if num_cols:
        questions.append(f"{num_cols[0]}의 평균은 얼마야?")
    if len(num_cols) > 1:
        questions.append(f"{num_cols[1]}이 가장 큰 상위 10건을 보여줘")

    return questions[:count]


def suggest_questions(con, count: int = 3) -> list[str]:
    """
    현재 업로드된 파일의 실제 컬럼을 보고 물어볼 만한 질문을 만든다.
    파일마다 컬럼이 달라지므로 추천 질문도 매번 새로 생성해야 한다.
    실패하면 컬럼 이름만으로 만든 기본 질문으로 대체한다.
    """
    try:
        schema_str, _ = get_schema(con)
    except Exception:
        return []

    prompt = f"""
아래는 사용자가 방금 업로드한 데이터의 실제 스키마다.

{schema_str}

이 데이터에 대해 물어볼 만한 한국어 질문을 {count}개 만들어라.

규칙:
1. 반드시 위 스키마에 실제로 있는 컬럼만 사용한다. 없는 개념을 지어내지 않는다.
2. 집계/그룹/정렬처럼 SQL로 바로 답할 수 있는 질문으로 만든다.
3. "불량", "위험"처럼 기준이 모호한 표현은 쓰지 않는다.
4. 각 질문은 25자 이내로 짧게 쓴다.
5. 서로 다른 컬럼과 다른 유형(개수/평균/순위 등)을 다룬다.

문자열 배열 형태의 JSON 하나만 출력한다. 다른 텍스트는 넣지 않는다.
예: ["질문1", "질문2", "질문3"]
"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _extract_text(response).strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        parsed = json.loads(raw)
        questions = [str(q).strip() for q in parsed if str(q).strip()]
        if questions:
            return questions[:count]
    except Exception:
        # 추천 질문은 부가 기능이라, 실패해도 챗봇 자체는 쓸 수 있어야 한다.
        pass

    return _fallback_questions(con, count)


# =====================================
# 결과 요약 (Claude API)
# =====================================

SUMMARY_PREVIEW_ROWS = 30


def summarize_result(
    question: str, result: pl.DataFrame, total_rows: int | None = None
) -> str:
    """
    SQL 실행 결과를 한국어 한두 문장으로 요약한다.
    결과가 클 수 있으므로 프롬프트에는 앞부분 일부만 미리보기로 넣는다.

    total_rows: LIMIT으로 잘리기 전 실제 전체 매칭(또는 집계) 행수.
                넘기지 않으면 result 길이를 그대로 전체로 취급한다.
    """
    shown_rows = len(result)
    if total_rows is None:
        total_rows = shown_rows

    preview = (
        result.head(SUMMARY_PREVIEW_ROWS)
        if shown_rows > SUMMARY_PREVIEW_ROWS
        else result
    )

    if total_rows > shown_rows:
        # LIMIT 때문에 조회 자체가 잘린 경우 — 미리보기가 아니라
        # "더 많은 결과 중 일부만 가져왔다"는 걸 분명히 알려야 한다.
        preview_note = (
            f"(조건에 맞는 전체 {total_rows:,}행 중 상위 {shown_rows:,}행만 "
            f"조회됨, 그중 앞 {len(preview):,}행 미리보기)"
        )
    elif shown_rows > SUMMARY_PREVIEW_ROWS:
        preview_note = f"(전체 {total_rows:,}행 중 앞 {SUMMARY_PREVIEW_ROWS}행 미리보기)"
    else:
        preview_note = ""

    prompt = f"""
너는 데이터 분석 결과를 쉽게 설명하는 전문가다.

사용자 질문:
{question}

SQL 실행 결과 {preview_note}:
{json.dumps(preview.to_dicts(), ensure_ascii=False, default=str)}

규칙:
1. 한국어로 한두 문장으로 요약한다.
2. 숫자는 천 단위 쉼표를 사용한다.
3. 결과에 없는 내용은 추측하지 않는다.
4. 결과가 "질문의 기준이 명확하지 않습니다."라면 기준이 명확하지 않아 분석할 수 없다고 설명한다.
5. "조건에 맞는 전체"라고 표시되어 있다면, 실제로는 {total_rows:,}행이 조건에
   맞지만 화면에는 일부만 표시된다는 점을 답변에 분명히 언급한다.
6. 그 외의 미리보기 표시라면, 전체 {total_rows:,}행 중 일부만 보고 있다는
   점을 감안해서 설명한다.

요약:
"""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_text(response).strip()


# =====================================
# 메인 파이프라인
# =====================================

def answer_question(
    con,
    question: str,
    on_progress: Callable[[str], None] | None = None,
    spec_text: str = "",
) -> dict:
    """
    자연어 질문 하나를 SQL 생성 → 검증 → 실행 → 요약까지 처리한다.

    on_progress: 각 단계가 시작될 때마다 현재 단계를 설명하는 문자열로
                 호출되는 콜백. UI에서 실시간 진행 상황을 보여주고 싶을
                 때 넘긴다 (예: Streamlit st.status().write). 넘기지
                 않으면 아무 일도 하지 않는다.
    spec_text:   확정된 질의 명세(spec_store.format_specs_for_prompt 결과).
                 모호한 표현이라도 여기에 기준이 있으면 되묻지 않고 답한다.

    반환 형식:
    {
        "answer": str,               # 한두 문장 요약
        "data": list[dict],          # SQL 실행 결과 (행 단위 dict 리스트)
        "table": str,                # 조회한 테이블명
        "recognized_columns": list,  # 결과 컬럼 목록
        "sql": str,                  # 생성된 SQL
        "validation": str,           # 검증 결과
        "chart": dict,               # 시각화 힌트 {"type","x","y"} 또는 빈 dict
        "total_rows": int,           # LIMIT 적용 전 실제 전체 매칭/집계 행수
        "is_ambiguous": bool,        # 기준이 모호해 답을 보류했는지
        "ambiguous_ask": str,        # 보류 시 사용자에게 되물을 문장
    }

    is_ambiguous 가 True면 SQL을 실행하지 않고 바로 반환한다. 이때
    사용자의 명확화 답변을 받아 spec_store 에 명세로 저장해두면, 다음
    같은 질문부터는 spec_text 를 통해 정상적으로 답하게 된다.
    """

    def notify(message: str) -> None:
        if on_progress is not None:
            on_progress(message)

    def failed(answer: str, validation: str, sql: str = "") -> dict:
        """실행까지 가지 못한 경우의 공통 반환값."""
        return {
            "answer": answer,
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": sql,
            "validation": validation,
            "chart": {},
            "total_rows": 0,
            "is_ambiguous": False,
            "ambiguous_ask": "",
        }

    # 1. 현재 업로드된 파일의 스키마를 동적으로 읽기
    notify("스키마를 확인하고 있습니다.")
    try:
        schema_str, allowed_cols = get_schema(con)
    except Exception as e:
        return failed(
            "데이터가 아직 로드되지 않았습니다. 파일을 먼저 업로드해 주세요.",
            f"스키마 읽기 실패 - {e}",
        )

    # 2. SQL + 차트 힌트 생성
    notify("SQL과 차트를 생성하고 있습니다.")
    generated = generate_sql_and_chart(question, schema_str, spec_text)
    sql = generated["sql"]
    chart_hint = generated["chart"]

    # 2-1. 기준이 모호하면 여기서 멈추고 사용자에게 되묻는다.
    #      (정확도가 최우선이라 추측해서 답하지 않는다. 사용자가 알려준
    #       기준은 명세로 저장돼 다음 같은 질문부터 spec_text 로 들어온다.)
    ambiguous = generated.get("ambiguous")
    if ambiguous:
        ask = ambiguous.get("ask") or "어떤 기준으로 볼지 구체적으로 알려주세요."
        reason = ambiguous.get("reason") or "질문의 기준이 명확하지 않습니다."
        result = failed(reason, f"보류 - {reason}", sql)
        result["is_ambiguous"] = True
        result["ambiguous_ask"] = ask
        return result

    # 3. SQL 검증 (동적 컬럼 기반)
    notify("SQL을 검증하고 있습니다.")
    is_valid, error_message = validate_sql(sql, allowed_cols)
    if not is_valid:
        return failed(
            f"SQL 검증에 실패했습니다: {error_message}",
            f"실패 - {error_message}",
            sql,
        )

    # 4. 결과 행수 상한 적용 후 실행
    #    (수십 GB 규모 파일에서 LIMIT 없는 쿼리가 전체를 끌고 오지 않도록 방지)
    notify("데이터를 조회하고 있습니다.")
    exec_sql, limit_applied = _apply_row_limit(sql)
    try:
        raw_result = con.execute(exec_sql).pl()
    except Exception as e:
        return failed("SQL 실행 중 오류가 발생했습니다.", f"실행 오류 - {e}", sql)

    # 상한 적용 시 같이 실어 보낸 실제 전체 매칭 행수를 분리해낸다.
    # (LIMIT으로 잘려도 "실제로 몇 건이었는지"를 잃어버리지 않기 위함)
    if limit_applied and TOTAL_COUNT_COL in raw_result.columns:
        true_total = (
            int(raw_result[TOTAL_COUNT_COL][0]) if len(raw_result) > 0 else 0
        )
        result = raw_result.drop(TOTAL_COUNT_COL)
    else:
        true_total = len(raw_result)
        result = raw_result

    # 5. 차트 힌트를 실제 결과 컬럼과 대조해서 검증
    chart: dict = {}
    if chart_hint:
        chart_type = chart_hint.get("type")
        chart_x = chart_hint.get("x")
        chart_y = chart_hint.get("y")
        if (
            chart_type in {"bar", "line", "pie"}
            and chart_x in result.columns
            and chart_y in result.columns
        ):
            chart = {"type": chart_type, "x": chart_x, "y": chart_y}

    # 6. 결과 요약 (실제 전체 매칭 행수를 함께 전달)
    notify("결과를 요약하고 있습니다.")
    summary = summarize_result(question, result, total_rows=true_total)

    validation_msg = "통과"
    if true_total > len(result):
        validation_msg += (
            f" (조건에 맞는 전체 {true_total:,}행 중 상위 "
            f"{len(result):,}행만 조회됨)"
        )

    return {
        "answer": summary,
        "data": result.to_dicts(),
        "table": ALLOWED_TABLE,
        "recognized_columns": result.columns,
        "sql": sql,
        "validation": validation_msg,
        "chart": chart,
        "total_rows": true_total,
        "is_ambiguous": False,
        "ambiguous_ask": "",
    }
