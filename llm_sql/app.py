import streamlit as st
import polars as pl
import duckdb
import os
import requests
import re

# =====================================
# SQL 검증 설정
# =====================================

# =====================================
# SQL 검증 설정
# =====================================

ALLOWED_TABLE = "nand_health"

ALLOWED_COLUMNS = {#컬럼 확정 후 수정
    "unit_id",
    "model",
    "pe_cycle",
    "temperature_c",
    "error_count",
    "unstable_count",
    "capacity_gb",
    "usage_hours"
}

def validate_sql(sql: str):

    if not sql or not sql.strip():
        return False, "SQL이 생성되지 않았습니다."

    sql = sql.strip()
    sql_upper = sql.upper()

    # 1. 여러 SQL 문장 실행 방지
    if ";" in sql.rstrip(";"):
        return False, "여러 SQL 문장은 실행할 수 없습니다."

    # 2. SELECT만 허용
    if not re.match(r"^\s*SELECT\b", sql_upper):
        return False, "SELECT 문만 사용할 수 있습니다."

    # 3. 위험한 SQL 명령 차단
    forbidden_keywords = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
        "CREATE", "TRUNCATE", "ATTACH", "DETACH",
        "COPY", "EXPORT", "IMPORT"
    ]

    for keyword in forbidden_keywords:
        if re.search(rf"\b{keyword}\b", sql_upper):
            return False, f"{keyword} 명령은 사용할 수 없습니다."

    # =====================================
    # [수정] 문자열 리터럴 제거한 "검사 전용" SQL 생성
    # 컬럼/테이블 토큰 검사는 이 버전으로만 수행하고,
    # 실제 실행(con.execute)에는 원본 sql을 그대로 사용한다.
    # =====================================
    # 'It''s ok' 처럼 이스케이프된 작은따옴표(') 도 포함해서 안전하게 제거
    sql_for_check = re.sub(r"'(?:[^']|'')*'", "''", sql)

    # 4. 테이블 검사 (검사용 SQL 기준)
    table_pattern = r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    tables = re.findall(table_pattern, sql_for_check, re.IGNORECASE)

    for table in tables:
        if table.lower() != ALLOWED_TABLE:
            return False, f"허용되지 않은 테이블입니다: {table}"

    # 5. 컬럼 검사 (검사용 SQL 기준 — 리터럴 내부 값은 여기 안 걸림)
    column_pattern = r"\b[a-zA-Z_][a-zA-Z0-9_]*\b"
    tokens = re.findall(column_pattern, sql_for_check)

    alias_pattern = r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    aliases = set(
        alias.upper()
        for alias in re.findall(alias_pattern, sql_for_check, re.IGNORECASE)
    )

    sql_keywords = {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "ASC", "DESC",
        "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IN", "IS", "NULL",
        "BETWEEN", "LIKE", "CASE", "WHEN", "THEN", "ELSE", "END",
        "COUNT", "AVG", "SUM", "MAX", "MIN", "DISTINCT", "HAVING",
        "OVER", "PARTITION", "ROW_NUMBER", "RANK", "DENSE_RANK",
        "TRUE", "FALSE", "MESSAGE"
    }

    sql_functions = {
        "COUNT", "AVG", "SUM", "MAX", "MIN",
        "ROUND", "COALESCE", "CAST", "NULLIF"
    }

    for token in tokens:
        token_upper = token.upper()

        if token_upper in aliases:
            continue
        if token_upper in sql_keywords:
            continue
        if token_upper in sql_functions:
            continue
        if token.lower() == ALLOWED_TABLE:
            continue
        if token_upper in {"INTEGER", "BIGINT", "DOUBLE", "VARCHAR", "DECIMAL"}:
            continue

        if token.lower() not in ALLOWED_COLUMNS:
            if token_upper not in {"NAND_HEALTH"}:
                return False, f"허용되지 않은 컬럼 또는 식별자입니다: {token}"

    return True, ""

from openai import OpenAI

# =====================================
# 청크 업로드 함수
# =====================================

def upload_file_in_chunks(
    file_path,
    upload_server_url="http://127.0.0.1:8000"
):

    file_size = os.path.getsize(file_path)

    filename = os.path.basename(file_path)


    # 1. 업로드 초기화
    init_response = requests.post(
        f"{upload_server_url}/upload/init",

        data={
            "filename": filename,
            "file_size": file_size
        }
    )


    init_response.raise_for_status()


    upload_info = init_response.json()


    upload_id = upload_info["upload_id"]

    chunk_size = upload_info["chunk_size"]

    total_chunks = upload_info["total_chunks"]


    progress_bar = st.progress(0)

    status_text = st.empty()


    # 2. 청크 단위 업로드
    with open(file_path, "rb") as file:

        for chunk_index in range(total_chunks):

            chunk_data = file.read(chunk_size)


            response = requests.post(

                f"{upload_server_url}/upload/chunk",

                data={
                    "upload_id": upload_id,
                    "chunk_index": chunk_index
                },

                files={
                    "chunk": (
                        f"chunk_{chunk_index}",
                        chunk_data
                    )
                }
            )


            response.raise_for_status()


            progress = (
                chunk_index + 1
            ) / total_chunks


            progress_bar.progress(progress)


            status_text.text(
                f"업로드 중... "
                f"{chunk_index + 1}/{total_chunks} "
                f"청크 완료"
            )


    # 3. 업로드 완료
    complete_response = requests.post(

        f"{upload_server_url}/upload/complete",

        data={
            "upload_id": upload_id,
            "filename": filename,
            "total_chunks": total_chunks
        }
    )


    complete_response.raise_for_status()


    result = complete_response.json()


    progress_bar.progress(1.0)


    status_text.success(
        "대용량 파일 업로드 완료!"
    )


    return result["file_path"]
st.set_page_config(
    page_title="NAND Health Chatbot",
    page_icon="💾"
)

st.title("💾 NAND Health Data Chatbot")


# =====================================
# 데이터 입력 방식 선택
# =====================================

data_mode = st.radio(
    "데이터 입력 방식을 선택하세요",
    [
        "📁 파일 업로드",
        "🚀 대용량 Parquet 파일 사용"
    ]
)


# =====================================
# DuckDB 연결
# =====================================

@st.cache_resource
def get_duckdb_connection():

    return duckdb.connect()
con = get_duckdb_connection()




# =====================================
# 1. 일반 파일 업로드
# =====================================

if data_mode == "📁 파일 업로드":

    uploaded_file = st.file_uploader(
        "📁 NAND Health csv 파일을 업로드하세요",
        type=["csv"]
    )

    if uploaded_file is not None:

        with st.spinner("파일을 읽는 중..."):

            file_name = uploaded_file.name

            # CSV
            if file_name.endswith(".csv"):

                data = pl.read_csv(uploaded_file)

            
            # DuckDB에 등록
            con.register("uploaded_data", data)

            con.execute("""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT *
                FROM uploaded_data
            """)

        st.success("데이터 업로드 완료!")
        st.write(f"총 {data.height:,}개의 데이터가 있습니다.")

        with st.expander("📊 데이터 미리보기"):

            preview = con.execute(
                "SELECT * FROM nand_health LIMIT 100"
            ).pl()

            st.dataframe(preview)

# =====================================
# 2. 대용량 파일 브라우저 업로드
# =====================================

else:

    st.subheader(
        "🚀 대용량 파일 청크 업로드"
    )

    # HTML 파일 읽기
    with open(
        "large_upload.html",
        "r",
        encoding="utf-8"
    ) as file:

        html_code = file.read()


    # Streamlit 화면에 HTML 업로더 표시
    st.components.v1.html(
        html_code,
        height=500,
        scrolling=True
    )


    st.divider()


    st.subheader(
        "📂 업로드된 파일 연결"
    )


    if st.button(
        "🔄 최근 업로드 파일 가져오기"
    ):

        try:

            response = requests.get(
                "http://127.0.0.1:8000/upload/latest"
            )


            response.raise_for_status()


            upload_info = response.json()


            final_file_path = upload_info[
                "file_path"
            ]


            st.success(
                "최근 업로드 파일을 찾았습니다!"
            )


            st.write(
                f"파일명: {upload_info['filename']}"
            )


            st.write(
                f"파일 경로: {final_file_path}"
            )


            # =====================================
            # Parquet 데이터 연결
            # =====================================

            con.execute(
                f"""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT *
                FROM read_parquet(
                    '{final_file_path}'
                )
                """
            )


            st.success(
                "✅ 자동 생성된 Parquet를 DuckDB에 연결했습니다!"
            )


            count_result = con.execute(
                "SELECT COUNT(*) FROM nand_health"
            ).fetchone()[0]


            st.write(
                f"총 {count_result:,}개의 데이터가 있습니다."
            )


            with st.expander(
                "📊 데이터 미리보기"
            ):

                preview = con.execute(
                    "SELECT * FROM nand_health LIMIT 100"
                ).pl()


                st.dataframe(
                    preview
                )


        except Exception as e:

            st.error(
                "파일 연결 중 오류가 발생했습니다."
            )


            st.code(
                str(e)
            )


# =====================================
# API 키 확인
# =====================================
# =====================================
# API 키 확인
# =====================================

api_key = os.environ.get("OPENAI_API_KEY")

if not api_key:

    st.error("OPENAI_API_KEY가 설정되지 않았습니다.")

    st.stop()


client = OpenAI(api_key=api_key)


# =====================================
# 예시)컬럼 확정 후 수정
# =====================================

schema = """
테이블명: nand_health

컬럼 정의:

- unit_id
  의미: NAND 유닛 식별자
  사용자 표현: 유닛, NAND, 장치, 제품 번호

- pe_cycle
  의미: PE Cycle 횟수
  사용자 표현: PE Cycle, PE 사이클, PE, 쓰기 횟수

- unstable_count
  의미: NAND의 불안정 발생 횟수
  사용자 표현: 불안정 횟수, 불안정 발생, unstable

- model
  의미: NAND 모델명
  사용자 표현: 모델, 제품 모델

- capacity_gb
  의미: NAND 용량(GB)
  사용자 표현: 용량, 저장 용량, GB

- temperature_c
  의미: NAND 온도(섭씨)
  사용자 표현: 온도, 발열, 섭씨, 뜨거운 정도

- error_count
  의미: NAND에서 발생한 오류 횟수
  사용자 표현: 오류, 에러, 오류 횟수, 에러 횟수

- usage_hours
  의미: NAND 사용 시간
  사용자 표현: 사용 시간, 사용 기간
"""



# =====================================
# 질문 입력
# =====================================

question = st.chat_input(
    "예: PE Cycle이 300 이상인 유닛은 몇 개야?"
)


# =====================================
# 최근 업로드 Parquet 자동 연결
# =====================================

if os.path.exists(
    "upload_info.json"
):

    import json


    with open(
        "upload_info.json",
        "r",
        encoding="utf-8"
    ) as info_file:

        upload_info = json.load(
            info_file
        )


    final_file_path = upload_info[
        "file_path"
    ]


    if os.path.exists(
        final_file_path
    ):

        con.execute(
            f"""
            CREATE OR REPLACE VIEW nand_health AS
            SELECT *
            FROM read_parquet(
                '{final_file_path}'
            )
            """
        )
if question:

    st.chat_message("user").write(question)

    # =====================================
    # AI SQL 생성 #컬럼 확정후 수정
    # =====================================

    with st.spinner("AI가 SQL을 생성하는 중..."):

        prompt = f"""
너는 NAND Health 데이터 분석용 SQL 생성기다.

{schema}

사용자 질문:
{question}

==================================================
1. 역할
==================================================

너의 역할은 사용자의 자연어 질문을
DuckDB에서 실행 가능한 단 하나의 SELECT SQL 문으로 변환하는 것이다.

반드시 실제 데이터 테이블 nand_health의 실제 컬럼만 사용한다.

SQL을 생성할 때:
- 질문에 없는 조건을 추가하지 않는다.
- 컬럼 의미를 임의로 추측하지 않는다.
- schema에 없는 컬럼을 만들어내지 않는다.
- SQL에 설명문을 포함하지 않는다.
- 최종 출력은 SQL 문 하나만 출력한다.

==================================================
2. 실제 테이블
==================================================

테이블명:
nand_health

사용 가능한 실제 컬럼:

unit_id
model
pe_cycle
temperature_c
error_count
unstable_count
capacity_gb
usage_hours

==================================================
3. 컬럼 의미 매핑 규칙
==================================================

사용자의 표현이 아래 목록에 포함되면
반드시 해당 컬럼을 사용한다.

[오류 관련]
"오류"
"에러"
"오류 수치"
"에러 수치"
"오류 개수"
"에러 개수"
"오류 횟수"
"에러 횟수"
→ error_count

[불안정 관련]
"불안정"
"불안정 횟수"
"불안정 발생"
"unstable"
→ unstable_count

[온도 관련]
"온도"
"발열"
"뜨거운 정도"
"섭씨 온도"
"섭씨"
→ temperature_c

[PE Cycle 관련]
"PE"
"PE Cycle"
"PE 사이클"
"쓰기 횟수"
→ pe_cycle

[사용 시간 관련]
"사용 시간"
"사용 기간"
→ usage_hours

[용량 관련]
"용량"
"저장 용량"
"GB"
→ capacity_gb

[모델 관련]
"모델"
"제품 모델"
→ model

[유닛 관련]
"유닛"
"NAND"
"장치"
"제품 번호"
→ unit_id

==================================================
4. 절대 혼동하면 안 되는 컬럼
==================================================

오류와 불안정은 서로 다른 개념이다.

"오류", "에러"
→ error_count

"불안정", "unstable"
→ unstable_count

절대 다음과 같이 해석하지 않는다.

오류 → unstable_count ❌
불안정 → error_count ❌

온도와 오류도 서로 다른 개념이다.

온도 → temperature_c
오류 → error_count

사용 시간과 PE Cycle도 서로 다른 개념이다.

사용 시간 → usage_hours
PE Cycle → pe_cycle

==================================================
5. 질문에 명시된 조건만 사용
==================================================

사용자가 질문에서 언급하지 않은 조건을
임의로 추가하지 않는다.

예를 들어:

사용자:
"온도가 70도보다 높은 NAND는 몇 개야?"

올바른 SQL:
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c > 70;

잘못된 SQL:
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c > 70
AND error_count > 10;

오류 조건은 사용자가 말하지 않았으므로 추가하면 안 된다.

==================================================
6. 모호한 상태·고장·품질 표현 처리 규칙
==================================================

다음 표현은 특정 컬럼이나 조건으로 임의 해석하지 않는다.

[고장 및 고장 위험]
- 고장날 것 같은 NAND
- 고장 위험이 높은 NAND
- 고장 위험 NAND
- 고장 가능성이 높은 NAND
- 고장난 NAND
- 곧 고장날 NAND
- 문제가 발생할 NAND

[문제 및 이상 상태]
- 문제가 있는 NAND
- 문제가 많은 NAND
- 이상이 있는 NAND
- 이상 NAND
- 불량 NAND
- 불량이 많은 NAND
- 위험한 NAND

[상태 및 품질]
- 건강한 NAND
- 상태가 좋은 NAND
- 상태가 안 좋은 NAND
- 품질이 좋은 NAND
- 품질이 나쁜 NAND
- 성능이 좋은 NAND
- 성능이 나쁜 NAND

[수명 및 노후화]
- 수명이 얼마 남지 않은 NAND
- 오래된 NAND
- 노후된 NAND

==================================================
모호한 질문 처리 원칙
==================================================

위와 같은 표현만 있고 구체적인 수치 기준이나
명시적인 컬럼 조건이 없는 경우:

1. temperature_c를 임의로 선택하지 않는다.
2. error_count를 임의로 선택하지 않는다.
3. unstable_count를 임의로 선택하지 않는다.
4. pe_cycle을 임의로 선택하지 않는다.
5. usage_hours를 임의로 선택하지 않는다.
6. 여러 컬럼을 임의로 조합하지 않는다.
7. error_count > 0 조건을 임의로 추가하지 않는다.
8. unstable_count > 0 조건을 임의로 추가하지 않는다.
9. temperature_c > 특정 값 조건을 임의로 추가하지 않는다.
10. pe_cycle > 특정 값 조건을 임의로 추가하지 않는다.
11. usage_hours > 특정 값 조건을 임의로 추가하지 않는다.

구체적인 기준이 없는 모호한 질문은
반드시 다음 SQL을 출력한다.

SELECT '질문의 기준이 명확하지 않습니다.' AS message;

==================================================
구체적인 기준이 있는 경우
==================================================

질문에 명시된 구체적인 기준이 있으면
그 기준만 사용한다.

예시 1:

사용자 질문:
"고장날 것 같은 NAND는 몇 개야?"

→ 기준 없음
→ 반드시:

SELECT '질문의 기준이 명확하지 않습니다.' AS message;

예시 2:

사용자 질문:
"오류가 10개 이상이고 불안정 횟수가 5회 이상인
고장 위험 NAND는 몇 개야?"

→ 명시된 조건만 사용:

error_count >= 10
AND unstable_count >= 5

예상 SQL:

SELECT COUNT(*)
FROM nand_health
WHERE error_count >= 10
AND unstable_count >= 5;

예시 3:

사용자 질문:
"온도가 70도 이상인 NAND를 고장 위험으로 보고
몇 개야?"

→ 사용자가 온도 기준을 직접 제시했으므로:

SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;

예시 4:

사용자 질문:
"PE Cycle이 1000 이상인 오래된 NAND는 몇 개야?"

→ PE Cycle 기준만 사용:

SELECT COUNT(*)
FROM nand_health
WHERE pe_cycle >= 1000;

예시 5:

사용자 질문:
"사용 시간이 10000시간 이상인 NAND는 몇 개야?"

→ 사용 시간 기준만 사용:

SELECT COUNT(*)
FROM nand_health
WHERE usage_hours >= 10000;

==================================================
모호한 표현과 구체적 조건의 우선순위
==================================================

"고장", "위험", "불량", "상태가 안 좋다",
"건강하지 않다"와 같은 표현은
그 자체로 SQL 조건이 아니다.

반드시 질문에 명시된 구체적인 수치 조건만 사용한다.

예:

"고장날 것 같은 NAND 중에서 온도가 70도 이상인 것은 몇 개야?"

→ "고장날 것 같다"는 모호한 표현이므로 무시한다.
→ 명시된 온도 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;

예:

"문제가 있는 NAND 중 오류가 10개 이상인 것은 몇 개야?"

→ "문제가 있는 NAND"는 모호한 표현이므로 무시한다.
→ 명시된 오류 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE error_count >= 10;

예:

"건강한 NAND 중 사용 시간이 1000시간 이하인 것은 몇 개야?"

→ "건강한 NAND"는 모호한 표현이므로 무시한다.
→ 명시된 사용 시간 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE usage_hours <= 1000;

==================================================
7. 집계 규칙
==================================================

사용자가 요구한 집계 방식만 사용한다.

"몇 개"
"개수"
"몇 개의 NAND"
"몇 개의 유닛"
→ COUNT(*)

"평균"
→ AVG()

"합계"
→ SUM()

"최댓값"
"가장 높은 값"
→ MAX()

"최솟값"
"가장 낮은 값"
→ MIN()

예:

"온도의 평균"
→ AVG(temperature_c)

"오류 개수의 합계"
→ SUM(error_count)

"가장 높은 PE Cycle"
→ MAX(pe_cycle)

==================================================
8. NAND 개수와 오류 합계를 구분
==================================================

사용자가 NAND 또는 유닛의 개수를 물으면
COUNT(*)를 사용한다.

예:

"온도가 70도 이상인 NAND는 몇 개야?"
→ COUNT(*)

반면:

"오류의 총합은?"
→ SUM(error_count)

"오류가 발생한 NAND는 몇 개야?"
→ COUNT(*)
WHERE error_count > 0

==================================================
9. 그룹별 분석
==================================================

사용자가 "모델별", "모델마다"라고 하면
GROUP BY model을 사용한다.

예:

"모델별 NAND 개수"
→
SELECT model, COUNT(*) AS unit_count
FROM nand_health
GROUP BY model;

"모델별 평균 온도"
→
SELECT model, AVG(temperature_c) AS avg_temperature
FROM nand_health
GROUP BY model;

==================================================
10. 순위 표현
==================================================

"가장 높은"
"최고"
"상위"
"많은 순"

→ ORDER BY 해당값 DESC

"가장 낮은"
"최저"
"하위"
"적은 순"

→ ORDER BY 해당값 ASC

예:

"모델별 오류가 가장 많은 순서"
→
GROUP BY model
ORDER BY error_count DESC

==================================================
11. 조건 표현
==================================================

"이상"
→ >=

"초과"
"보다 높음"
→ >

"이하"
→ <=

"미만"
"보다 낮음"
→ <

"같음"
→ =

"아닌"
→ !=

"그리고"
→ AND

"또는"
→ OR

예:

"온도가 70도 이상이고 오류가 10개 초과"
→
temperature_c >= 70
AND error_count > 10

==================================================
12. SQL 작성 규칙
==================================================

1. 반드시 SELECT로 시작한다.
2. 테이블명은 반드시 nand_health를 사용한다.
3. FROM nand_health를 사용한다.
4. schema에 존재하는 컬럼만 사용한다.
5. SELECT, WHERE, GROUP BY, ORDER BY의 모든 컬럼은 실제 컬럼이어야 한다.
6. DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE 등을 사용하지 않는다.
7. 여러 SQL 문장을 출력하지 않는다.
8. SQL 설명문을 출력하지 않는다.
9. Markdown 코드 블록을 사용하지 않는다.
10. SQL 하나만 출력한다.
11. 사용자의 질문에 없는 조건을 추가하지 않는다.
12. 사용자의 표현을 가장 먼저 컬럼 의미 매핑 규칙과 비교한다.

==================================================
13. SQL 생성 전 최종 점검
==================================================

SQL을 출력하기 전에 반드시 다음을 확인한다.

[컬럼 점검]
- 모든 컬럼이 schema에 존재하는가?

[의미 점검]
- 오류를 error_count로 매핑했는가?
- 불안정을 unstable_count로 매핑했는가?
- 온도를 temperature_c로 매핑했는가?
- PE Cycle을 pe_cycle로 매핑했는가?
- 사용 시간을 usage_hours로 매핑했는가?

[조건 점검]
- 사용자가 말하지 않은 조건을 추가하지 않았는가?

[집계 점검]
- 개수는 COUNT(*)인가?
- 평균은 AVG()인가?
- 합계는 SUM()인가?
- 최댓값은 MAX()인가?
- 최솟값은 MIN()인가?

[테이블 점검]
- nand_health만 사용했는가?

[안전 점검]
- SELECT 문 하나만 출력하는가?

==================================================
14. 최종 출력
==================================================

최종 답변에는 SQL 코드만 출력한다.

SQL:
"""

        response = client.chat.completions.create(
               model="gpt-4o-mini",
              messages=[
                 {
                      "role": "system",
                       "content": "너는 정확한 SQL을 생성하는 데이터 분석 전문가다."
                   },
                 {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )
    
        sql = response.choices[0].message.content.strip()
    
        sql = sql.replace("```sql", "")
        sql = sql.replace("```", "")
        sql = sql.strip()
    
    
    # =====================================
    # 생성된 SQL 표시
    # =====================================
    
    st.subheader("🧠 AI가 생성한 SQL")
    
    st.code(
        sql,
        language="sql"
    )
    
    
    # =====================================
    # SQL 검증 및 실행
    # =====================================
    
    try:
    
        is_valid, error_message = validate_sql(sql)
    
        if not is_valid:
    
            st.error(
                f"❌ SQL 검증 실패: {error_message}"
            )
    
            st.stop()
    
    
        result = con.execute(sql).pl()
    
    
        # =====================================
        # 분석 결과
        # =====================================
    
        st.subheader("📊 분석 결과")
    
        st.dataframe(result)
    
    
        # =====================================
        # AI 결과 요약
        # =====================================
    
        result_text = str(result)
    
        summary_prompt = f"""
    너는 NAND Health 데이터 분석 결과를 쉽게 설명하는 분석 전문가다.
    
    사용자 질문:
    {question}
    
    SQL 실행 결과:
    {result_text}
    
    규칙:
    1. 결과를 한국어로 한두 문장으로 요약한다.
    2. 숫자는 가능한 한 천 단위 쉼표를 사용한다.
    3. 결과에 없는 내용은 추측하지 않는다.
    4. 분석 결과만 간결하게 설명한다.
    5. 결과가 "질문의 기준이 명확하지 않습니다."라면
       기준이 명확하지 않아 분석할 수 없다고 설명한다.
    
    요약:
    """
    
    
        summary_response = client.chat.completions.create(
    
            model="gpt-4o-mini",
    
            messages=[
    
                {
                    "role": "user",
                    "content": summary_prompt
                }
    
            ],
    
            temperature=0
    
        )
    
    
        summary = (
            summary_response
            .choices[0]
            .message.content
            .strip()
        )
    
    
        st.subheader("💡 AI 분석 요약")
    
        st.info(summary)
    
    
        # =====================================
        # 단일 결과면 Metric 또는 메시지 표시
        # =====================================
    
        if (
            result.shape[0] == 1
            and result.shape[1] == 1
        ):
    
            value = result.item(
                row=0,
                column=0
            )
    
    
            # 숫자인 경우
            if isinstance(value, (int, float)):
    
                st.metric(
    
                    label="분석 결과",
    
                    value=f"{value:,.0f}"
    
                )
    
    
            # 문자열인 경우
            else:
    
                st.info(
                    str(value)
                )
    
    
    except Exception as e:
    
        st.error(
            "SQL 실행 중 오류가 발생했습니다."
         )
    
        st.code(
            str(e)
        )