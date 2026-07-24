import streamlit as st
import polars as pl
import duckdb
import os
from openai import OpenAI

st.set_page_config(
    page_title="NAND Health Chatbot",
    page_icon="💾"
)

st.title("💾 NAND Health Data Chatbot")


    # 파일 업로드
uploaded_file = st.file_uploader(
    "📁 NAND Health CSV 파일을 업로드하세요",
    type=["csv"]
)

# 파일이 업로드되었을 때
if uploaded_file is not None:

    with st.spinner("데이터를 읽고 Parquet으로 변환하는 중..."):

        # 업로드된 CSV를 임시 파일로 저장
        temp_csv = "uploaded_nand_health.csv"

        with open(temp_csv, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # CSV를 Polars로 읽기
        data = pl.read_csv(temp_csv)

        # Parquet으로 변환
        parquet_file = "uploaded_nand_health.parquet"

        data.write_parquet(
            parquet_file,
            compression="zstd"
        )

    st.success("NAND Health 데이터 업로드 및 Parquet 변환 완료!")
    st.write(f"총 {data.height:,}개의 데이터가 있습니다.")

    # DuckDB 연결
    con = duckdb.connect()

    # Parquet을 nand_health라는 이름으로 연결
    con.execute(f"""
        CREATE OR REPLACE VIEW nand_health AS
        SELECT * FROM '{parquet_file}'
    """)

    # 데이터 미리보기
    with st.expander("📊 데이터 미리보기"):

        preview = con.execute(
            "SELECT * FROM nand_health LIMIT 100"
        ).pl()

        st.dataframe(preview)

# API 키 확인
api_key = os.environ.get("OPENAI_API_KEY")

if not api_key:
    st.error("OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = OpenAI(api_key=api_key)

# 컬럼 설명
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

question = st.chat_input(
    "예: PE Cycle이 300 이상인 유닛은 몇 개야?"
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

        # Markdown 코드 블록 제거
        sql = sql.replace("```sql", "")
        sql = sql.replace("```", "")
        sql = sql.strip()

    st.subheader("🧠 AI가 생성한 SQL")
    st.code(sql, language="sql")

    try:

        # SQL 안전성 검증
        sql_lower = sql.lower().strip()

        # SELECT만 허용
        if not sql_lower.startswith("select"):
            st.error("SELECT 문만 실행할 수 있습니다.")
            st.stop()

        # 위험한 SQL 명령어 차단
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
        # 결과를 문자열로 변환
        result_text = str(result)

        # AI에게 결과 요약 요청
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

               # 결과가 하나의 숫자만 반환된 경우
        if result.shape[0] == 1 and result.shape[1] == 1:

            value = result[0, 0]

            st.metric(
                label="분석 결과",
                value=f"{value:,}"
            )

        # 여러 행의 결과면 막대그래프 표시
        elif result.shape[0] > 1 and result.shape[1] >= 2:

            st.bar_chart(result)

    except Exception as e:

        st.error("SQL 실행 중 오류가 발생했습니다.")

        st.code(str(e))