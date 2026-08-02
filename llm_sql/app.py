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
            )
            resp.raise_for_status()
            progress_bar.progress((idx + 1) / total_chunks)
            status_text.text(f"업로드 중... {idx + 1}/{total_chunks} 청크 완료")

    complete_resp = requests.post(
        f"{upload_server_url}/upload/complete",
        data={"upload_id": upload_id, "filename": filename, "total_chunks": total_chunks},
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
    "STRFTIME", "DATE", "YEAR", "MONTH", "DAY",
    "UPPER", "LOWER", "TRIM", "LENGTH",
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
3. SELECT 문 하나만 출력한다.
4. DROP, DELETE, UPDATE, INSERT, ALTER, CREATE 등은 절대 사용하지 않는다.
5. 질문에 없는 조건을 임의로 추가하지 않는다.
6. Markdown 코드 블록(```sql)을 사용하지 않는다.
7. SQL 설명문을 포함하지 않는다.

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

SQL:
"""


def generate_sql(question: str, schema: str) -> str:
    """자연어 질문을 nand_health 테이블에 대한 SELECT SQL 문 하나로 변환한다."""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system="너는 정확한 SQL을 생성하는 데이터 분석 전문가다.",
        messages=[{"role": "user", "content": _build_sql_prompt(question, schema)}],
        temperature=0,
    )
    sql = response.content[0].text.strip()
    sql = re.sub(r"```sql|```", "", sql).strip()
    return sql


# =====================================
# 결과 요약 (Claude API)
# =====================================

def summarize_result(question: str, result: pl.DataFrame) -> str:
    """SQL 실행 결과를 한국어 한두 문장으로 요약한다."""
    prompt = f"""
너는 데이터 분석 결과를 쉽게 설명하는 전문가다.

사용자 질문:
{question}

SQL 실행 결과:
{result}

규칙:
1. 한국어로 한두 문장으로 요약한다.
2. 숫자는 천 단위 쉼표를 사용한다.
3. 결과에 없는 내용은 추측하지 않는다.
4. 결과가 "질문의 기준이 명확하지 않습니다."라면 기준이 명확하지 않아 분석할 수 없다고 설명한다.

요약:
"""
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
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
        "chart": dict,               # 시각화 힌트 (현재는 빈 dict)
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

    # 2. SQL 생성
    sql = generate_sql(question, schema_str)

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

    # 4. SQL 실행
    try:
        result = con.execute(sql).pl()
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

    # 5. 결과 요약
    summary = summarize_result(question, result)

    return {
        "answer": summary,
        "data": result.to_dicts(),
        "table": ALLOWED_TABLE,
        "recognized_columns": result.columns,
        "sql": sql,
        "validation": "통과",
        "chart": {},
    }
