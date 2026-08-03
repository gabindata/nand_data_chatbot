from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image

# llm_sql 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llm_sql"))
from app import (
    get_duckdb_connection,
    load_into_duckdb,
    connect_latest_parquet,
    answer_question,
)

# 대용량 파일은 브라우저가 이 주소의 FastAPI 서버로 직접 청크 업로드한다.
UPLOAD_SERVER_URL = os.environ.get("UPLOAD_SERVER_URL", "http://127.0.0.1:8000")


_CHUNK_UPLOADER_TEMPLATE = """
<div style="font-family: -apple-system, sans-serif; font-size: 13px;">
  <input type="file" id="sunnyFileInput" accept=".csv"
         style="width: 100%; margin-bottom: 8px;" />
  <button id="sunnyUploadBtn"
          style="width: 100%; padding: 8px; border-radius: 8px;
                 border: 1px solid #8bbed5; background: #fff; cursor: pointer;">
    업로드 시작
  </button>
  <div style="margin-top: 8px;">
    <progress id="sunnyProgress" value="0" max="100" style="width: 100%;"></progress>
    <div id="sunnyStatus" style="color: #4a6b78; margin-top: 4px;">파일을 선택하세요.</div>
  </div>
</div>
<script>
const SERVER_URL = "__SERVER_URL__";

document.getElementById("sunnyUploadBtn").addEventListener("click", async () => {
  const fileInput = document.getElementById("sunnyFileInput");
  const file = fileInput.files[0];
  const status = document.getElementById("sunnyStatus");
  const progressBar = document.getElementById("sunnyProgress");

  if (!file) {
    status.innerText = "파일을 먼저 선택하세요.";
    return;
  }
  if (!file.name.toLowerCase().endsWith(".csv")) {
    status.innerText = "CSV 파일만 업로드할 수 있습니다.";
    return;
  }

  status.innerText = "업로드 초기화 중...";

  const initData = new FormData();
  initData.append("filename", file.name);
  initData.append("file_size", file.size);

  let initResponse;
  try {
    initResponse = await fetch(SERVER_URL + "/upload/init", { method: "POST", body: initData });
  } catch (error) {
    status.innerText = "FastAPI 서버(" + SERVER_URL + ")에 연결할 수 없습니다.";
    return;
  }

  if (!initResponse.ok) {
    status.innerText = "업로드 초기화 실패";
    return;
  }

  const uploadInfo = await initResponse.json();
  const uploadId = uploadInfo.upload_id;
  const totalChunks = uploadInfo.total_chunks;
  const chunkSize = uploadInfo.chunk_size;

  for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
    const start = chunkIndex * chunkSize;
    const end = Math.min(start + chunkSize, file.size);
    const chunk = file.slice(start, end);

    const chunkData = new FormData();
    chunkData.append("upload_id", uploadId);
    chunkData.append("chunk_index", chunkIndex);
    chunkData.append("chunk", chunk, "chunk_" + chunkIndex);

    try {
      const chunkResp = await fetch(SERVER_URL + "/upload/chunk", { method: "POST", body: chunkData });
      if (!chunkResp.ok) {
        status.innerText = (chunkIndex + 1) + "번째 청크 업로드 실패";
        return;
      }
    } catch (error) {
      status.innerText = "업로드 중 연결이 끊어졌습니다.";
      return;
    }

    const progress = ((chunkIndex + 1) / totalChunks) * 100;
    progressBar.value = progress;
    status.innerText = "업로드 중... " + (chunkIndex + 1) + " / " + totalChunks + " 청크";
  }

  const completeData = new FormData();
  completeData.append("upload_id", uploadId);
  completeData.append("filename", file.name);
  completeData.append("total_chunks", totalChunks);

  const completeResponse = await fetch(SERVER_URL + "/upload/complete", { method: "POST", body: completeData });
  if (!completeResponse.ok) {
    status.innerText = "업로드 완료 처리 실패 (CSV → Parquet 변환 오류일 수 있음)";
    return;
  }

  progressBar.value = 100;
  status.innerText = "업로드 완료! 아래 '업로드한 데이터 불러오기' 버튼을 눌러주세요.";
});
</script>
"""


def build_chunk_uploader_html(server_url: str) -> str:
    """브라우저가 Streamlit 서버를 거치지 않고 FastAPI 서버로 직접
    청크 업로드하는 컴포넌트. 대용량(수십 GB) 파일이 Streamlit 프로세스
    메모리를 거치지 않도록 하기 위함이다."""
    return _CHUNK_UPLOADER_TEMPLATE.replace("__SERVER_URL__", server_url)


# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_PATH = BASE_DIR / "assets" / "sunny_bg.png"
AVATAR_PATH = BASE_DIR / "assets" / "sunny_avatar.png"

st.set_page_config(
    page_title="SUNNY 9조 데이터 챗봇",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


background_base64 = image_to_base64(BACKGROUND_PATH)
sunny_avatar = Image.open(AVATAR_PATH)


# ---------------------------------------------------------
# 디자인
# ---------------------------------------------------------
st.markdown(
    f"""
    <style>
    :root {{
        --sunny-red: #ef3b32;
        --sunny-red-dark: #d92f27;
        --sunny-blue: #39a9db;
        --sunny-navy: #163f56;
        --glass: rgba(255, 255, 255, 0.82);
        --glass-strong: rgba(255, 255, 255, 0.93);
        --border: rgba(255, 255, 255, 0.90);
    }}

    #MainMenu, footer {{
        visibility: hidden;
    }}

    header[data-testid="stHeader"] {{
        background: transparent;
    }}

    .stApp {{
        background-image:
            linear-gradient(rgba(223, 247, 255, 0.12), rgba(223, 247, 255, 0.12)),
            url("data:image/png;base64,{background_base64}");
        background-size: cover;
        background-position: center center;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }}

    [data-testid="stAppViewContainer"] {{
        background: transparent;
    }}

    [data-testid="stMain"] {{
        background: transparent;
    }}

    .block-container {{
        max-width: 980px;
        min-height: calc(100vh - 48px);
        margin-top: 18px;
        margin-bottom: 22px;
        padding: 1.6rem 2.25rem 7.8rem 2.25rem;
        border: 1px solid var(--border);
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.78);
        backdrop-filter: blur(22px);
        -webkit-backdrop-filter: blur(22px);
        box-shadow: 0 24px 70px rgba(27, 91, 123, 0.20);
    }}

    [data-testid="stSidebar"] {{
        background: rgba(255, 255, 255, 0.78);
        backdrop-filter: blur(22px);
        -webkit-backdrop-filter: blur(22px);
        border-right: 1px solid rgba(255, 255, 255, 0.90);
        box-shadow: 10px 0 34px rgba(31, 92, 122, 0.12);
    }}

    [data-testid="stSidebarContent"] {{
        padding-top: 1.15rem;
    }}

    .brand-kicker {{
        margin: 0 0 2px 0;
        color: var(--sunny-red);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.10em;
    }}

    .brand-title {{
        margin: 0;
        color: var(--sunny-navy);
        font-size: 21px;
        line-height: 1.15;
        font-weight: 900;
    }}

    .brand-subtitle {{
        margin: 4px 0 0 0;
        color: #6e8794;
        font-size: 12px;
    }}

    .hero {{
        padding: 2px 2px 20px 2px;
        border-bottom: 1px solid rgba(84, 145, 173, 0.14);
        margin-bottom: 1rem;
    }}

    .hero-badge {{
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 6px 10px;
        border-radius: 999px;
        color: #167ca4;
        background: rgba(225, 247, 255, 0.88);
        border: 1px solid rgba(87, 184, 220, 0.24);
        font-size: 12px;
        font-weight: 750;
        margin-bottom: 10px;
    }}

    .hero-title {{
        margin: 0;
        color: var(--sunny-navy);
        font-size: 29px;
        font-weight: 900;
        letter-spacing: -0.04em;
    }}

    .hero-description {{
        margin: 7px 0 0 0;
        color: #668493;
        font-size: 14px;
        line-height: 1.65;
    }}

    .welcome-card {{
        margin: 14px 0 22px 0;
        padding: 25px 22px;
        text-align: center;
        border-radius: 23px;
        background: rgba(255, 255, 255, 0.74);
        border: 1px solid rgba(255, 255, 255, 0.92);
        box-shadow: 0 12px 36px rgba(30, 102, 138, 0.09);
    }}

    .welcome-title {{
        color: #1d536e;
        font-size: 19px;
        font-weight: 850;
        margin-bottom: 6px;
    }}

    .welcome-text {{
        color: #708b98;
        font-size: 13px;
        line-height: 1.7;
    }}

    .data-card {{
        margin-top: 8px;
        padding: 13px 14px;
        border-radius: 15px;
        background: rgba(255, 255, 255, 0.80);
        border: 1px solid rgba(113, 170, 197, 0.18);
        box-shadow: 0 8px 22px rgba(32, 93, 124, 0.07);
    }}

    .status-line {{
        display: flex;
        align-items: center;
        gap: 8px;
        color: #28576c;
        font-size: 13px;
        font-weight: 780;
    }}

    .status-dot {{
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #25b96f;
        box-shadow: 0 0 0 4px rgba(37, 185, 111, 0.12);
    }}

    .data-meta {{
        margin-top: 8px;
        color: #79909b;
        font-size: 11px;
        line-height: 1.65;
    }}

    [data-testid="stChatMessage"] {{
        margin-bottom: 0.75rem;
        padding: 1rem 1.05rem;
        border: 1px solid rgba(181, 216, 231, 0.60);
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.86);
        box-shadow: 0 9px 26px rgba(35, 94, 124, 0.08);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
    }}

    [data-testid="stChatMessageAvatarAssistant"] img,
    [data-testid="stChatMessageAvatarUser"] img {{
        border: 2px solid white;
        box-shadow: 0 4px 14px rgba(31, 86, 113, 0.16);
    }}

    [data-testid="stChatInput"] {{
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(139, 190, 213, 0.55);
        box-shadow: 0 14px 38px rgba(26, 86, 115, 0.18);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
    }}

    [data-testid="stStatusWidget"] {{
        border-radius: 16px;
        border: 1px solid rgba(113, 183, 214, 0.30);
        background: rgba(241, 251, 255, 0.90);
    }}

    [data-testid="stDataFrame"] {{
        border: 1px solid rgba(130, 181, 204, 0.28);
        border-radius: 14px;
        overflow: hidden;
    }}

    details {{
        border-radius: 14px !important;
    }}

    .stButton > button {{
        width: 100%;
        min-height: 43px;
        border: 1px solid rgba(112, 170, 196, 0.30);
        border-radius: 13px;
        background: rgba(255, 255, 255, 0.84);
        color: #24566e;
        font-weight: 750;
        transition: all 0.16s ease;
    }}

    .stButton > button:hover {{
        color: var(--sunny-red);
        border-color: rgba(239, 59, 50, 0.42);
        transform: translateY(-1px);
        box-shadow: 0 7px 20px rgba(239, 59, 50, 0.10);
    }}

    .quick-title {{
        margin: 4px 0 8px 2px;
        color: #718b98;
        font-size: 12px;
        font-weight: 750;
    }}

    @media (max-width: 768px) {{
        .block-container {{
            margin: 0;
            padding: 1.1rem 1rem 7.4rem 1rem;
            border-radius: 0;
            min-height: 100vh;
        }}

        .hero-title {{
            font-size: 24px;
        }}
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 상태 관리
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

if "con" not in st.session_state:
    st.session_state.con = get_duckdb_connection()

if "data_loaded" not in st.session_state:
    st.session_state.data_loaded = False

if "row_count" not in st.session_state:
    st.session_state.row_count = 0


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending_prompt = None


# ---------------------------------------------------------
# 사이드바
# ---------------------------------------------------------
with st.sidebar:
    col_avatar, col_name = st.columns([0.85, 2.15], vertical_alignment="center")

    with col_avatar:
        st.image(sunny_avatar, width=66)

    with col_name:
        st.markdown(
            """
            <p class="brand-kicker">SUNNY 9 TEAM</p>
            <p class="brand-title">써니 9조</p>
            <p class="brand-subtitle">품질 데이터 분석 챗봇</p>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    if st.button("＋ 새 채팅", use_container_width=True):
        reset_chat()
        st.rerun()

    st.markdown("##### 최근 대화")

    if st.session_state.messages:
        user_messages = [
            message["content"]
            for message in st.session_state.messages
            if message["role"] == "user"
        ]
        for title in reversed(user_messages[-5:]):
            st.caption(f"• {title[:24]}")
    else:
        st.caption("아직 대화 기록이 없습니다.")

    st.markdown("---")
    st.markdown("##### 데이터 업로드")

    uploaded_file = st.file_uploader(
        "CSV 파일을 선택하세요",
        type=["csv"],
        label_visibility="collapsed",
    )

    if uploaded_file is not None:
        if uploaded_file.size > 500 * 1024 * 1024:
            st.warning(
                "500MB가 넘는 파일은 메모리 사용량이 커서 느리거나 실패할 수 "
                "있습니다. 아래 '대용량 파일 업로드'를 이용해 주세요."
            )
        with st.spinner("데이터 로드 중..."):
            try:
                row_count = load_into_duckdb(st.session_state.con, uploaded_file)
                st.session_state.data_loaded = True
                st.session_state.row_count = row_count
                st.session_state.messages = []
            except Exception as e:
                st.error(f"파일 로드 실패: {e}")

    if st.session_state.data_loaded:
        st.markdown(
            f"""
            <div class="data-card">
                <div class="status-line">
                    <span class="status-dot"></span>
                    CSV 데이터 연결 완료
                </div>
                <div class="data-meta">
                    총 행 수: {st.session_state.row_count:,}행<br>
                    조회 방식: 자연어 → SQL
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.caption("파일을 업로드하면 질문할 수 있습니다.")

    st.markdown("---")
    with st.expander("대용량 파일 업로드 (10GB+)"):
        st.caption(
            "브라우저가 Streamlit을 거치지 않고 아래 서버로 직접 파일을 "
            "전송합니다. 먼저 backend 서버를 실행해 주세요:"
        )
        st.code("uvicorn backend.upload_server:app --port 8000", language="bash")
        st.iframe(build_chunk_uploader_html(UPLOAD_SERVER_URL), height=150)

        if st.button("업로드한 데이터 불러오기", use_container_width=True):
            with st.spinner("최근 업로드된 데이터를 연결하는 중..."):
                try:
                    connect_latest_parquet(st.session_state.con, UPLOAD_SERVER_URL)
                    row_count = st.session_state.con.execute(
                        "SELECT COUNT(*) FROM nand_health"
                    ).fetchone()[0]
                    st.session_state.data_loaded = True
                    st.session_state.row_count = row_count
                    st.session_state.messages = []
                    st.success(f"연결 완료: 총 {row_count:,}행")
                except Exception as e:
                    st.error(f"연결 실패: {e}")

    st.markdown("---")
    st.caption("SUNNY 9조 · v1.0")


# ---------------------------------------------------------
# 데모 파이프라인
# 실제 API 연결 시 이 함수만 교체하면 됩니다.
# ---------------------------------------------------------
def create_demo_result(question: str) -> tuple[str, pd.DataFrame, dict[str, Any]]:
    lowered = question.lower()

    if "월" in question or "추이" in question:
        df = pd.DataFrame(
            {
                "월": ["1월", "2월", "3월", "4월", "5월", "6월"],
                "불량건수": [22, 18, 25, 16, 13, 11],
            }
        )
        answer = (
            "월별 불량 건수는 3월에 25건으로 가장 높았고, "
            "4월부터 감소하여 6월에는 11건으로 확인됩니다."
        )
        chart = {"type": "line", "x": "월", "y": "불량건수"}

    elif "제품" in question or "ufs" in lowered or "emmc" in lowered:
        df = pd.DataFrame(
            {
                "제품군": ["UFS", "eMMC", "SSD", "NAND"],
                "LVD 불량건수": [18, 11, 8, 14],
            }
        )
        answer = (
            "제품군별 LVD 불량 건수를 조회한 결과 UFS가 18건으로 가장 많았습니다. "
            "다음은 NAND 14건, eMMC 11건, SSD 8건 순입니다."
        )
        chart = {"type": "bar", "x": "제품군", "y": "LVD 불량건수"}

    else:
        df = pd.DataFrame(
            {
                "공정": ["A 공정", "B 공정", "C 공정", "D 공정"],
                "불량률(%)": [1.8, 2.7, 1.2, 2.1],
            }
        )
        answer = (
            "조회 결과 B 공정의 불량률이 2.7%로 가장 높았습니다. "
            "실제 API가 연결되면 이 영역에 데이터 기반 답변이 표시됩니다."
        )
        chart = {"type": "bar", "x": "공정", "y": "불량률(%)"}

    verification = {
        "table": "quality_data",
        "recognized_columns": [chart["x"], chart["y"]],
        "sql": (
            f"SELECT {chart['x']}, SUM({chart['y']}) AS result "
            f"FROM quality_data GROUP BY {chart['x']};"
        ),
        "validation": "UI 데모용 검증 완료",
        "row_count": len(df),
        "chart": chart,
    }

    return answer, df, verification


def render_chart(df: pd.DataFrame, chart: dict[str, str]) -> None:
    chart_type = chart.get("type")
    x_column = chart.get("x")
    y_column = chart.get("y")

    if not x_column or not y_column:
        st.info("그래프 설정이 없습니다.")
        return

    if chart_type == "line":
        figure = px.line(
            df,
            x=x_column,
            y=y_column,
            markers=True,
        )
    elif chart_type == "pie":
        figure = px.pie(
            df,
            names=x_column,
            values=y_column,
        )
    else:
        figure = px.bar(
            df,
            x=x_column,
            y=y_column,
            text_auto=True,
        )

    figure.update_layout(
        margin=dict(l=12, r=12, t=22, b=10),
        height=340,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.55)",
        font=dict(size=13),
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
        config={"displayModeBar": False},
    )


def render_assistant_message(message: dict[str, Any]) -> None:
    st.markdown(message["content"])

    data = message.get("data")
    if data:
        df = pd.DataFrame(data)

        tab_answer, tab_table, tab_chart = st.tabs(
            ["핵심 결과", "데이터 표", "시각화"]
        )

        with tab_answer:
            verification = message.get("verification", {})
            st.markdown(
                f"""
                **선택한 테이블**  
                `{verification.get("table", "확인되지 않음")}`

                **인식한 컬럼**  
                `{", ".join(verification.get("recognized_columns", []))}`

                **조회 행 수**  
                `{verification.get("row_count", len(df))}개`
                """
            )

        with tab_table:
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

        with tab_chart:
            render_chart(
                df,
                message.get("verification", {}).get("chart", {}),
            )

        with st.expander("SQL 및 검증 정보"):
            st.caption(
                message.get("verification", {}).get(
                    "validation",
                    "검증 상태를 확인할 수 없습니다.",
                )
            )
            st.code(
                message.get("verification", {}).get(
                    "sql",
                    "SQL 정보가 없습니다.",
                ),
                language="sql",
            )


# ---------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------
st.markdown(
    """
    <section class="hero">
        <div class="hero-badge">● CSV 데이터 연결 완료</div>
        <h1 class="hero-title">SUNNY 데이터 챗봇</h1>
        <p class="hero-description">
            품질 데이터를 자연어로 검색하고, 조회 결과를 표와 그래프로 확인하세요.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    st.markdown(
        """
        <div class="welcome-card">
            <div class="welcome-title">안녕하세요! 써니가 데이터를 찾아드릴게요 ☀️</div>
            <div class="welcome-text">
                아래 추천 질문을 누르거나 채팅창에 직접 질문해 보세요.<br>
                현재는 화면 확인을 위한 데모 데이터가 연결되어 있습니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="quick-title">추천 질문</div>', unsafe_allow_html=True)
    q1, q2, q3 = st.columns(3)

    with q1:
        if st.button("제품군별 LVD 불량 건수", use_container_width=True):
            st.session_state.pending_prompt = "제품군별 LVD 불량 건수를 보여줘"
            st.rerun()

    with q2:
        if st.button("월별 불량 추이", use_container_width=True):
            st.session_state.pending_prompt = "월별 불량 건수 추이를 보여줘"
            st.rerun()

    with q3:
        if st.button("공정별 불량률 비교", use_container_width=True):
            st.session_state.pending_prompt = "공정별 불량률을 비교해줘"
            st.rerun()


for message in st.session_state.messages:
    avatar = sunny_avatar if message["role"] == "assistant" else "👤"

    with st.chat_message(message["role"], avatar=avatar):
        if message["role"] == "assistant":
            render_assistant_message(message)
        else:
            st.markdown(message["content"])


typed_prompt = st.chat_input("품질 데이터에 대해 질문해 주세요.")
prompt = st.session_state.pending_prompt or typed_prompt

if prompt:
    st.session_state.pending_prompt = None

    user_message = {
        "role": "user",
        "content": prompt,
    }
    st.session_state.messages.append(user_message)

    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=sunny_avatar):
        completed_steps: list[str] = []

        if not st.session_state.data_loaded:
            st.warning("사이드바에서 CSV 파일을 먼저 업로드해 주세요.")
            st.stop()

        with st.status("질문을 처리하고 있습니다.", expanded=True) as status:
            status.write("⏳ 스키마를 확인하고 있습니다.")
            status.write("⏳ 자연어 질문을 SQL로 변환하고 있습니다.")

            result = answer_question(st.session_state.con, prompt)

            status.update(
                label="분석이 완료되었습니다.",
                state="complete",
                expanded=False,
            )

        assistant_message = {
            "role": "assistant",
            "content": result["answer"],
            "data": result["data"],
            "verification": {
                "table": result["table"],
                "recognized_columns": result["recognized_columns"],
                "sql": result["sql"],
                "validation": result["validation"],
                "row_count": len(result["data"]),
                "chart": result.get("chart", {}),
            },
            "steps": completed_steps,
        }

        render_assistant_message(assistant_message)
        st.session_state.messages.append(assistant_message)
