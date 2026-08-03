"""
NAND Health 챗봇의 AI+SQL 로직 모듈.

컬럼이 매번 달라지는 파일을 처리하기 위해 스키마를 하드코딩하지 않고
파일이 로드된 DuckDB 뷰에서 동적으로 읽는다.

제공 함수:
- get_duckdb_connection(): DuckDB 커넥션 생성
- load_into_duckdb(con, file): CSV/Parquet 파일을 nand_health 뷰로 등록
- connect_latest_parquet(con, url): backend 서버의 최신 parquet을 뷰로 연결
- upload_file_in_chunks(file_path, url): 대용량 파일을 청크 업로드
- get_schema(con): 현재 nand_health 뷰의 컬럼 목록과 타입을 반환
- answer_question(con, question): 자연어 → SQL 생성 → 검증 → 실행 → 요약
"""

from __future__ import annotations

import json
import os
import re
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
    nand_health 뷰로 등록한다. 반환값은 로드된 행 수.
    """
    if isinstance(file, (str, os.PathLike)):
        path = str(file)
        if path.lower().endswith(".parquet"):
            con.execute(f"""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT * FROM read_parquet('{path}')
            """)
        else:
            con.execute(f"""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT * FROM read_csv_auto('{path}')
            """)
    else:
        # Streamlit UploadedFile 등 파일 객체인 경우
        data = pl.read_csv(file)
        con.register("_uploaded_data", data)
        con.execute("""
            CREATE OR REPLACE VIEW nand_health AS
            SELECT * FROM _uploaded_data
        """)

    row_count = con.execute("SELECT COUNT(*) FROM nand_health").fetchone()[0]
    return row_count


def connect_latest_parquet(con, upload_server_url: str = "http://127.0.0.1:8000") -> str:
    """
    backend/upload_server.py 에 최근 업로드된 parquet 파일을
    nand_health 뷰로 연결한다. 연결한 parquet 파일 경로를 반환한다.
    """
    response = requests.get(f"{upload_server_url}/upload/latest", timeout=3)
    response.raise_for_status()
    file_path = response.json()["file_path"]

    con.execute(f"""
        CREATE OR REPLACE VIEW nand_health AS
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
    현재 nand_health 뷰의 컬럼 정보를 DuckDB에서 동적으로 읽는다.

    반환:
        schema_str   — Claude 프롬프트에 넣을 스키마 설명 문자열
        allowed_cols — validate_sql 에 사용할 허용 컬럼 집합 (소문자)
    """
    rows = con.execute("DESCRIBE nand_health").fetchall()
    # rows: [(column_name, column_type, null, key, default, extra), ...]

    schema_lines = ["테이블명: nand_health\n", "컬럼 목록:"]
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

ALLOWED_TABLE = "nand_health"

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

    # 컬럼 검사 — 동적 화이트리스트
    aliases = {
        a.upper()
        for a in re.findall(
            r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_for_check, re.IGNORECASE
        )
    }
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", sql_for_check)

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


def _apply_row_limit(sql: str, max_rows: int = MAX_RESULT_ROWS) -> tuple[str, bool]:
    """
    수십 GB 규모 데이터에서 LIMIT 없는 쿼리가 결과를 통째로 끌고 오지
    않도록 상한을 강제한다. 이미 LIMIT이 있으면 그대로 둔다.
    반환: (실행할 SQL, 상한을 새로 적용했는지 여부)
    """
    s = sql.strip().rstrip(";").strip()
    if re.search(r"\bLIMIT\s+\d+\b", s, re.IGNORECASE):
        return s, False
    return f"{s} LIMIT {max_rows}", True


# =====================================
# SQL 생성 (Claude API)
# =====================================

def _build_sql_prompt(question: str, schema: str) -> str:
    return f"""
너는 데이터 분석용 SQL 생성기다.

아래는 현재 업로드된 파일의 실제 스키마다:

{schema}

사용자 질문:
{question}

==================================================
규칙
==================================================

1. 위 스키마에 존재하는 컬럼만 사용한다.
2. 테이블명은 반드시 nand_health 만 사용한다.
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

모호한 질문 (구체적 수치 기준 없이 "고장", "불량", "위험" 등만 있는 경우):
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

{{"sql": "<SELECT 문>", "chart": {{"type": "bar", "x": "<컬럼명>", "y": "<컬럼명>"}} 또는 null}}
"""


def generate_sql_and_chart(question: str, schema: str) -> dict:
    """
    자연어 질문을 nand_health 테이블에 대한 SELECT SQL 문과 차트 힌트로 변환한다.
    반환: {"sql": str, "chart": dict | None}
    """
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=(
            "너는 정확한 SQL과 시각화 힌트를 생성하는 데이터 분석 전문가다. "
            "반드시 순수 JSON 객체 하나만 출력한다."
        ),
        messages=[{"role": "user", "content": _build_sql_prompt(question, schema)}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # JSON 파싱에 실패하면 통짜 텍스트를 SQL로 간주하고 차트는 포기한다.
        return {"sql": raw, "chart": None}

    sql = str(parsed.get("sql", "")).strip()
    chart = parsed.get("chart")
    if not isinstance(chart, dict):
        chart = None
    return {"sql": sql, "chart": chart}


# =====================================
# 결과 요약 (Claude API)
# =====================================

SUMMARY_PREVIEW_ROWS = 30


def summarize_result(question: str, result: pl.DataFrame) -> str:
    """
    SQL 실행 결과를 한국어 한두 문장으로 요약한다.
    결과가 클 수 있으므로 프롬프트에는 앞부분 일부만 미리보기로 넣는다.
    """
    total_rows = len(result)
    truncated = total_rows > SUMMARY_PREVIEW_ROWS
    preview = result.head(SUMMARY_PREVIEW_ROWS) if truncated else result

    preview_note = (
        f"(전체 {total_rows:,}행 중 앞 {SUMMARY_PREVIEW_ROWS}행 미리보기)"
        if truncated
        else ""
    )

    prompt = f"""
너는 데이터 분석 결과를 쉽게 설명하는 전문가다.

사용자 질문:
{question}

SQL 실행 결과 {preview_note}:
{preview}

규칙:
1. 한국어로 한두 문장으로 요약한다.
2. 숫자는 천 단위 쉼표를 사용한다.
3. 결과에 없는 내용은 추측하지 않는다.
4. 결과가 "질문의 기준이 명확하지 않습니다."라면 기준이 명확하지 않아 분석할 수 없다고 설명한다.
5. 미리보기라고 표시되어 있다면, 전체 {total_rows:,}행 중 일부만 보고 있다는 점을 감안해서 설명한다.

요약:
"""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# =====================================
# 메인 파이프라인
# =====================================

def answer_question(con, question: str) -> dict:
    """
    자연어 질문 하나를 SQL 생성 → 검증 → 실행 → 요약까지 처리한다.

    반환 형식:
    {
        "answer": str,               # 한두 문장 요약
        "data": list[dict],          # SQL 실행 결과 (행 단위 dict 리스트)
        "table": str,                # 조회한 테이블명
        "recognized_columns": list,  # 결과 컬럼 목록
        "sql": str,                  # 생성된 SQL
        "validation": str,           # 검증 결과
        "chart": dict,               # 시각화 힌트 {"type","x","y"} 또는 빈 dict
    }
    """
    # 1. 현재 업로드된 파일의 스키마를 동적으로 읽기
    try:
        schema_str, allowed_cols = get_schema(con)
    except Exception as e:
        return {
            "answer": "데이터가 아직 로드되지 않았습니다. 파일을 먼저 업로드해 주세요.",
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": "",
            "validation": f"스키마 읽기 실패 - {e}",
            "chart": {},
        }

    # 2. SQL + 차트 힌트 생성
    generated = generate_sql_and_chart(question, schema_str)
    sql = generated["sql"]
    chart_hint = generated["chart"]

    # 3. SQL 검증 (동적 컬럼 기반)
    is_valid, error_message = validate_sql(sql, allowed_cols)
    if not is_valid:
        return {
            "answer": f"SQL 검증에 실패했습니다: {error_message}",
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": sql,
            "validation": f"실패 - {error_message}",
            "chart": {},
        }

    # 4. 결과 행수 상한 적용 후 실행
    #    (수십 GB 규모 파일에서 LIMIT 없는 쿼리가 전체를 끌고 오지 않도록 방지)
    exec_sql, limit_applied = _apply_row_limit(sql)
    try:
        result = con.execute(exec_sql).pl()
    except Exception as e:
        return {
            "answer": "SQL 실행 중 오류가 발생했습니다.",
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": sql,
            "validation": f"실행 오류 - {e}",
            "chart": {},
        }

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

    # 6. 결과 요약
    summary = summarize_result(question, result)

    validation_msg = "통과"
    if limit_applied and len(result) >= MAX_RESULT_ROWS:
        validation_msg += f" (결과가 많아 상위 {MAX_RESULT_ROWS:,}행만 조회됨)"

    return {
        "answer": summary,
        "data": result.to_dicts(),
        "table": ALLOWED_TABLE,
        "recognized_columns": result.columns,
        "sql": sql,
        "validation": validation_msg,
        "chart": chart,
    }
