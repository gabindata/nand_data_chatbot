import streamlit as st
import polars as pl
import duckdb
import os
import requests

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
        "📁 NAND Health 파일을 업로드하세요",
        type=["csv", "xlsx"]
    )

    if uploaded_file is not None:

        with st.spinner("파일을 읽는 중..."):

            file_name = uploaded_file.name

            # CSV
            if file_name.endswith(".csv"):

                data = pl.read_csv(uploaded_file)

            # Excel
            elif file_name.endswith(".xlsx"):

                data = pl.read_excel(uploaded_file)

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
# 컬럼 설명
# =====================================

schema = """
테이블명: nand_health

컬럼:
- unit_id: NAND 유닛 식별자
- pe_cycle: PE Cycle 횟수
- unstable_count: 불안정 횟수
- model: 모델명
- capacity_gb: 용량(GB)
- temperature_c: 온도(섭씨)
- error_count: 오류 횟수
- usage_hours: 사용 시간
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

    with st.spinner("AI가 SQL을 생성하는 중..."):

        prompt = f"""
너는 NAND Health 데이터 분석용 SQL 생성기다.

{schema}

사용자 질문:
{question}

규칙:
1. DuckDB에서 실행 가능한 SQL만 출력한다.
2. 테이블명은 반드시 nand_health를 사용한다.
3. 위에 정의된 컬럼만 사용한다.
4. SQL 코드 외의 설명은 출력하지 않는다.
5. 집계 질문에는 COUNT, AVG, SUM, MAX, MIN 등을 사용한다.
6. 유닛 개수를 물으면 COUNT(*)를 사용한다.
7. 모델별 분석을 요청하면 GROUP BY model을 사용한다.

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


    st.subheader("🧠 AI가 생성한 SQL")

    st.code(sql, language="sql")


    try:

        sql_lower = sql.lower().strip()


        # SELECT만 허용
        if not sql_lower.startswith("select"):

            st.error("SELECT 문만 실행할 수 있습니다.")

            st.stop()


        # 위험한 SQL 차단
        forbidden_words = [
            "drop",
            "delete",
            "update",
            "insert",
            "alter",
            "create",
            "truncate",
            "attach",
            "copy"
        ]


        for word in forbidden_words:

            if word in sql_lower:

                st.error(
                    f"안전하지 않은 SQL 명령어가 감지되었습니다: {word}"
                )

                st.stop()


        # SQL 실행
        result = con.execute(sql).pl()


        st.subheader("📊 분석 결과")

        st.dataframe(result)


        # 결과 요약
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


        summary = summary_response.choices[0].message.content.strip()


        st.subheader("💡 AI 분석 요약")

        st.info(summary)


        # 숫자 하나만 반환
        if result.shape[0] == 1 and result.shape[1] == 1:

            value = result[0, 0]

            st.metric(
                label="분석 결과",
                value=f"{value:,}"
            )


        # 여러 행이면 숫자 컬럼만 그래프



    except Exception as e:

        st.error("SQL 실행 중 오류가 발생했습니다.")

        st.code(str(e))