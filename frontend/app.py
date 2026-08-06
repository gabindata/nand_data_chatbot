from __future__ import annotations

import base64
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

# llm_sql 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llm_sql"))
from app import (
    get_duckdb_connection,
    load_into_duckdb,
    connect_latest_parquet,
    answer_question,
    suggest_questions,
)
from spec_store import (
    add_spec,
    delete_spec,
    format_specs_for_prompt,
    load_specs,
    update_spec,
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

  const startTime = Date.now();

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

    const uploadedBytes = end;
    const elapsedSec = (Date.now() - startTime) / 1000;
    const progress = (uploadedBytes / file.size) * 100;
    progressBar.value = progress;

    let statusText = "업로드 중... " + (chunkIndex + 1) + " / " + totalChunks
      + " 청크 (" + formatBytes(uploadedBytes) + " / " + formatBytes(file.size) + ")";

    // 초반 1초 미만은 속도가 불안정해서 ETA를 생략한다.
    if (elapsedSec > 1 && uploadedBytes < file.size) {
      const bytesPerSec = uploadedBytes / elapsedSec;
      const remainingSec = (file.size - uploadedBytes) / bytesPerSec;
      statusText += " · 약 " + formatDuration(remainingSec) + " 남음";
    }
    status.innerText = statusText;
  }

  // 청크 전송은 끝났지만 서버가 CSV → Parquet 변환을 하는 동안은
  // 정확한 진행률을 알 수 없어 progress bar를 불확정(애니메이션) 상태로 바꾼다.
  progressBar.removeAttribute("value");
  status.innerText = "청크 전송 완료. 서버에서 CSV → Parquet 변환 중입니다... "
    + "(파일 크기 기준 약 " + formatDuration(estimateConversionSeconds(file.size)) + " 예상, "
    + "실제 소요 시간은 서버 성능에 따라 다를 수 있습니다)";

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

function formatBytes(bytes) {
  if (bytes >= 1024 * 1024 * 1024) {
    return (bytes / (1024 * 1024 * 1024)).toFixed(1) + "GB";
  }
  return (bytes / (1024 * 1024)).toFixed(0) + "MB";
}

function formatDuration(seconds) {
  if (!isFinite(seconds) || seconds < 0) {
    return "계산 중";
  }
  if (seconds < 60) {
    return Math.max(1, Math.round(seconds)) + "초";
  }
  const minutes = Math.floor(seconds / 60);
  const remainSec = Math.round(seconds % 60);
  return minutes + "분 " + remainSec + "초";
}

// 서버 디스크/CPU 성능에 따라 실제와 다를 수 있는 대략적인 추정치.
// (로컬 SSD 기준 스트리밍 변환 처리량을 대략 150MB/s로 가정)
function estimateConversionSeconds(fileSizeBytes) {
  const ASSUMED_THROUGHPUT = 150 * 1024 * 1024;
  return fileSizeBytes / ASSUMED_THROUGHPUT;
}
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
    page_title="써니 9조 데이터 챗봇",
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
        height: 100vh;
        overflow: hidden;
    }}

    /* stMain을 세로 flex 컨테이너로 만들어, 결과 영역(.block-container)과
       채팅 입력창(stBottom 계열)이 서로 다른 두 개의 flex 아이템이 되도록 한다.
       이렇게 하면 입력창은 항상 화면 맨 아래에 "고정"되고, 결과 영역만 그
       위에서 독립적으로 스크롤되어 입력창이 결과를 가리는 문제가 근본적으로
       사라진다. (Claude 채팅 UI와 동일한 레이아웃 방식) */
    [data-testid="stMain"] {{
        background: transparent;
        height: 100vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }}

    [data-testid="stMain"] > div {{
        height: 100%;
        display: flex;
        flex-direction: column;
        min-height: 0;
    }}

    .block-container {{
        max-width: 980px;
        width: 100%;
        margin: 18px auto 0 auto;
        padding: 1.6rem 2.25rem 1.6rem 2.25rem;
        border: 1px solid var(--border);
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.78);
        backdrop-filter: blur(22px);
        -webkit-backdrop-filter: blur(22px);
        box-shadow: 0 24px 70px rgba(27, 91, 123, 0.20);
        /* flex 아이템으로서 남는 공간을 모두 차지하고, 내부에서만 스크롤 */
        flex: 1 1 auto;
        min-height: 0;
        overflow-y: auto;
        overscroll-behavior: contain;
    }}

    /* 채팅 입력창을 감싸는 컨테이너는 flex의 두 번째 아이템으로 두어
       block-container 아래, 화면 맨 밑에 항상 자리잡게 한다. Streamlit
       버전에 따라 data-testid가 다를 수 있어 두 가지를 모두 지정한다. */
    [data-testid="stBottom"],
    [data-testid="stBottomBlockContainer"] {{
        position: relative !important;
        flex: 0 0 auto;
        width: 100%;
        max-width: 980px;
        margin: 0 auto;
        z-index: 5;
        background: transparent;
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
        color: #1f9d63;
        background: rgba(224, 250, 238, 0.88);
        border: 1px solid rgba(37, 185, 111, 0.28);
        font-size: 12px;
        font-weight: 750;
        margin-bottom: 10px;
    }}

    .hero-badge--offline {{
        color: #7a8b93;
        background: rgba(238, 242, 244, 0.88);
        border: 1px solid rgba(150, 165, 172, 0.28);
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
        border-radius: 26px;
        background: rgba(255, 255, 255, 0.96);
        border: 1.5px solid rgba(150, 160, 168, 0.55);
        box-shadow: 0 14px 38px rgba(26, 86, 115, 0.18);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        transition: border-color 0.15s ease;
    }}

    /* 내부 요소(텍스트 영역 등)도 같은 곡률을 갖도록 강제해,
       클릭 시 빨간 스트로크가 바깥 테두리와 동일한 라운드를 유지하게 한다. */
    [data-testid="stChatInput"] > div,
    [data-testid="stChatInput"] textarea {{
        border-radius: 26px !important;
    }}

    /* 둥근 모서리(pill 형태) 곡선에 커서가 걸려 가려지는 것을 막기 위해
       텍스트 시작 위치를 안쪽으로 밀어준다 (스페이스 한 칸 누른 효과). */
    [data-testid="stChatInput"] textarea {{
        padding-left: 14px !important;
    }}

    [data-testid="stChatInput"]:focus-within {{
        border-color: var(--sunny-red) !important;
    }}

    /* Streamlit 기본 테마가 안쪽 div에도 포커스 시 자체 테두리(테마
       primaryColor)를 그리는데, 바깥 컨테이너보다 살짝 작은 크기에
       같은 border-radius를 써서 두 겹 테두리의 곡률이 어긋나 보인다.
       바깥 테두리 하나만 보이도록 안쪽 테두리는 항상 투명 처리한다. */
    [data-testid="stChatInput"] > div {{
        border-color: transparent !important;
    }}

    /* 어시스턴트 답변 요약 텍스트를 담는 박스. 블러 없이 단색 배경 +
       회색 테두리로 눈에 띄게 감싼다. */
    .answer-summary {{
        margin: 10px 0 4px 0;
        padding: 14px 16px;
        border: 1px solid #c7d4da;
        border-radius: 14px;
        background: #f2f9fb;
        color: #26495b;
        font-size: 14.5px;
        line-height: 1.75;
    }}

    .answer-summary .stat-highlight {{
        color: var(--sunny-red-dark);
        font-weight: 800;
    }}

    /* 탭 콘텐츠(핵심 결과 / 데이터 표 / 시각화) 영역을 단색 테두리로 강조.
       블러 없이 깔끔한 단색 배경 + 테두리만 사용한다. */
    [data-testid="stTabs"] [role="tabpanel"] {{
        margin-top: 10px;
        padding: 16px 18px;
        border: 1px solid #c7d4da;
        border-radius: 14px;
        background: #ffffff;
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

    /* ---- 기준이 모호해 답을 보류했을 때 보여주는 카드 ---- */
    .clarify-card {{
        margin: 10px 0 4px 0;
        padding: 14px 16px;
        border: 1px solid #e6b8b4;
        border-left: 4px solid var(--sunny-red);
        border-radius: 14px;
        background: #fdf4f3;
        color: #7d3a35;
        font-size: 14.5px;
        line-height: 1.75;
    }}

    .clarify-title {{
        display: block;
        margin-bottom: 4px;
        color: var(--sunny-red-dark);
        font-size: 13px;
        font-weight: 800;
    }}

    .clarify-ask {{
        display: block;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px dashed rgba(217, 47, 39, 0.28);
        color: #5f2f2b;
        font-weight: 700;
    }}

    /* ---- 오른쪽 질의 명세서 패널 ----
       .block-container 가 스크롤 컨테이너이므로, 그 안에서 sticky를 주면
       대화가 길어져도 패널이 오른쪽에 계속 붙어 있는다. 패널 자체가 길어질
       때는 패널 안에서만 스크롤되게 한다. */
    .st-key-spec_panel {{
        position: sticky;
        top: 0;
        align-self: flex-start;
        max-height: calc(100vh - 210px);
        overflow-y: auto;
        overscroll-behavior: contain;
        padding-right: 6px;
    }}

    .spec-panel-title {{
        margin: 2px 0;
        color: var(--sunny-navy);
        font-size: 16px;
        font-weight: 850;
    }}

    .spec-empty {{
        margin-top: 12px;
        padding: 18px 14px;
        text-align: center;
        color: #7c94a0;
        font-size: 12.5px;
        line-height: 1.7;
        border-radius: 14px;
        border: 1px dashed rgba(113, 170, 197, 0.40);
        background: rgba(255, 255, 255, 0.55);
    }}

    @keyframes specSlideIn {{
        from {{ opacity: 0; transform: translateX(16px); }}
        to {{ opacity: 1; transform: translateX(0); }}
    }}

    .spec-card {{
        margin-top: 12px;
        padding: 12px 13px;
        border-radius: 14px;
        background: #ffffff;
        border: 1px solid #c7d4da;
    }}

    .spec-card-highlight {{
        animation: specSlideIn 0.45s ease;
        border-color: rgba(239, 59, 50, 0.45);
        box-shadow: 0 8px 22px rgba(239, 59, 50, 0.12);
    }}

    .spec-card-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 6px;
        margin-bottom: 6px;
    }}

    .spec-index {{
        color: var(--sunny-blue);
        font-size: 11.5px;
        font-weight: 800;
    }}

    .spec-badge {{
        padding: 3px 8px;
        border-radius: 999px;
        font-size: 10.5px;
        font-weight: 750;
        white-space: nowrap;
        color: var(--sunny-red-dark);
        background: rgba(239, 59, 50, 0.12);
    }}

    .spec-question {{
        color: #55707d;
        font-size: 12.5px;
        line-height: 1.55;
        margin-bottom: 4px;
    }}

    .spec-answer {{
        color: var(--sunny-navy);
        font-size: 13px;
        font-weight: 700;
        line-height: 1.55;
    }}

    .spec-meta {{
        margin-top: 6px;
        color: #96acb6;
        font-size: 10.5px;
    }}

    @media (max-width: 768px) {{
        .block-container {{
            margin: 0;
            padding: 1.1rem 1rem 1.1rem 1rem;
            border-radius: 0;
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

# 방금 처리한 file_uploader 파일의 식별자. 같은 파일이 매 rerun마다
# 반복 처리되는 것을 막기 위한 용도.
if "loaded_file_id" not in st.session_state:
    st.session_state.loaded_file_id = None

# 추천 질문은 업로드된 파일의 컬럼에 따라 달라지므로 파일을 새로 올릴 때마다
# 다시 만든다. (고정 질문을 두면 컬럼이 다른 파일에서 전부 헛질문이 된다)
if "suggested_questions" not in st.session_state:
    st.session_state.suggested_questions = []

# 답변이 새로 추가된 직후 한 번만 맨 아래로 스크롤하기 위한 플래그
if "scroll_to_bottom" not in st.session_state:
    st.session_state.scroll_to_bottom = False

# "최근 대화"에서 특정 질문을 클릭했을 때 그 위치로 스크롤하기 위한 대상 id
if "scroll_to_message_id" not in st.session_state:
    st.session_state.scroll_to_message_id = None

# 질의 명세서 — 파일에 영구 저장되므로 세션 시작 시 한 번 읽어온다.
if "specs" not in st.session_state:
    st.session_state.specs = load_specs()

# 기준이 모호해 답을 보류한 질문. 다음 사용자 입력을 이 질문에 대한
# 명확화 답변으로 해석하기 위해 들고 있는다.
if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = None

if "show_spec_panel" not in st.session_state:
    st.session_state.show_spec_panel = False

# 방금 추가된 명세를 패널에서 강조 표시하기 위한 id
if "latest_spec_id" not in st.session_state:
    st.session_state.latest_spec_id = None


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    st.session_state.pending_clarification = None


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
            <p class="brand-kicker">SUNI TEAM</p>
            <p class="brand-title">써니 9조</p>
            <p class="brand-subtitle">데이터 분석 챗봇</p>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    if st.button("＋ 새 채팅", use_container_width=True):
        reset_chat()
        st.rerun()

    st.markdown("##### 최근 대화")

    user_messages = [
        message
        for message in st.session_state.messages
        if message["role"] == "user"
    ]

    if user_messages:
        for message in reversed(user_messages[-5:]):
            title = message["content"]
            label = title if len(title) <= 24 else title[:24] + "…"
            if st.button(
                f"💬 {label}",
                key=f"jump_{message['id']}",
                use_container_width=True,
            ):
                st.session_state.scroll_to_message_id = message["id"]
                st.rerun()
    else:
        st.caption("아직 대화 기록이 없습니다.")

    st.markdown("---")
    st.markdown("##### 데이터 업로드")

    uploaded_file = st.file_uploader(
        "CSV 파일을 선택하세요",
        type=["csv"],
        label_visibility="collapsed",
    )

    # file_uploader는 사용자가 파일을 바꾸지 않는 한 매 rerun마다 같은
    # UploadedFile을 계속 반환한다. file_id로 "이미 처리한 파일인지"를
    # 확인하지 않으면, 채팅 메시지를 보내거나 버튼을 누를 때마다 CSV를
    # 통째로 다시 읽고 추천 질문까지 Claude를 다시 호출하게 되어 모든
    # 상호작용이 매번 몇 배로 느려진다.
    if uploaded_file is not None and uploaded_file.file_id != st.session_state.loaded_file_id:
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
                st.session_state.loaded_file_id = uploaded_file.file_id
                st.session_state.suggested_questions = suggest_questions(
                    st.session_state.con
                )
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
        components.html(build_chunk_uploader_html(UPLOAD_SERVER_URL), height=150)

        if st.button("업로드한 데이터 불러오기", use_container_width=True):
            with st.spinner("최근 업로드된 데이터를 연결하는 중..."):
                try:
                    connect_latest_parquet(st.session_state.con, UPLOAD_SERVER_URL)
                    row_count = st.session_state.con.execute(
                        "SELECT COUNT(*) FROM uploaded_data"
                    ).fetchone()[0]
                    st.session_state.data_loaded = True
                    st.session_state.row_count = row_count
                    st.session_state.messages = []
                    st.session_state.suggested_questions = suggest_questions(
                        st.session_state.con
                    )
                    st.success(f"연결 완료: 총 {row_count:,}행")
                except Exception as e:
                    st.error(f"연결 실패: {e}")

    st.markdown("---")
    st.caption("써니 9조 · v1.0")


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


_NUMBER_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)(건|%|원|개|명|위|년|월|일|배)?"
)


def highlight_numbers(text: str) -> str:
    """텍스트 내 숫자(및 붙은 단위)를 <span>으로 감싸 강조 표시한다."""

    def _wrap(match: re.Match) -> str:
        number, unit = match.group(1), match.group(2) or ""
        return f'<span class="stat-highlight">{number}{unit}</span>'

    return _NUMBER_PATTERN.sub(_wrap, text)


def render_spec_panel() -> None:
    """오른쪽 질의 명세서 패널. 확정된 해석 기준이 쌓이는 곳."""
    with st.container(key="spec_panel"):
        st.markdown(
            '<div class="spec-panel-title">📋 질의 명세서</div>',
            unsafe_allow_html=True,
        )
        st.caption("기준이 모호했던 질문에 답해주시면 여기에 쌓이고, 다음부터는 되묻지 않습니다.")

        specs = st.session_state.specs
        if not specs:
            st.markdown(
                """
                <div class="spec-empty">
                    아직 확정된 기준이 없습니다.<br>
                    챗봇이 되물었을 때 답해주시면<br>
                    여기에 자동으로 추가됩니다.
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        keyword = st.text_input(
            "명세 검색",
            placeholder="질문 또는 기준으로 검색",
            label_visibility="collapsed",
            key="spec_search",
        )

        shown = 0
        for index, entry in enumerate(reversed(specs), start=1):
            haystack = (
                f"{entry.get('trigger_question', '')} {entry.get('clarification', '')}"
            ).lower()
            if keyword and keyword.lower() not in haystack:
                continue

            shown += 1
            is_latest = entry.get("id") == st.session_state.latest_spec_id
            badge = '<span class="spec-badge">방금 추가됨</span>' if is_latest else ""

            # 마크다운은 빈 줄을 만나면 HTML 블록을 끊고 나머지를 본문 텍스트로
            # 취급한다. 배지처럼 비어 있을 수 있는 값이 있으므로 줄바꿈 없이
            # 한 줄로 이어 붙인다.
            st.markdown(
                f'<div class="spec-card{" spec-card-highlight" if is_latest else ""}">'
                f'<div class="spec-card-head">'
                f'<span class="spec-index">#{len(specs) - index + 1}</span>{badge}'
                f"</div>"
                f'<div class="spec-question">Q. {entry.get("trigger_question", "")}</div>'
                f'<div class="spec-answer">→ {entry.get("clarification", "")}</div>'
                f'<div class="spec-meta">{entry.get("created_at", "")} 확정</div>'
                f"</div>",
                unsafe_allow_html=True,
            )

            with st.expander("상세 / 삭제"):
                if entry.get("ambiguous_reason"):
                    st.caption(f"보류 사유: {entry['ambiguous_reason']}")
                if entry.get("resolved_sql"):
                    st.code(entry["resolved_sql"], language="sql")
                if st.button("이 명세 삭제", key=f"del_{entry.get('id')}"):
                    delete_spec(entry["id"])
                    st.session_state.specs = load_specs()
                    st.rerun()

        if keyword and shown == 0:
            st.caption("검색 결과가 없습니다.")


def render_assistant_message(message: dict[str, Any]) -> None:
    # 기준이 모호해 답을 보류한 경우 — 결과 대신 되묻는 카드를 보여준다.
    if message.get("is_ambiguous"):
        ask = message.get("ambiguous_ask", "")
        ask_html = f'<span class="clarify-ask">{ask}</span>' if ask else ""
        st.markdown(
            f'<div class="clarify-card">'
            f'<span class="clarify-title">🔒 정확도를 위해 답변을 보류했습니다</span>'
            f'{message["content"]}{ask_html}'
            f"</div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div class="answer-summary">{highlight_numbers(message["content"])}</div>',
        unsafe_allow_html=True,
    )

    data = message.get("data")
    if data:
        df = pd.DataFrame(data)

        tab_answer, tab_table, tab_chart = st.tabs(
            ["핵심 결과", "데이터 표", "시각화"]
        )

        with tab_answer:
            verification = message.get("verification", {})
            row_count = verification.get("row_count", len(df))
            total_rows = verification.get("total_rows", row_count)

            row_count_line = f"`{row_count:,}개`"
            if total_rows > row_count:
                row_count_line += f" (조건에 맞는 전체 `{total_rows:,}개` 중 상위 {row_count:,}개만 조회됨)"

            st.markdown(
                f"""
                **선택한 테이블**  
                `{verification.get("table", "확인되지 않음")}`

                **인식한 컬럼**  
                `{", ".join(verification.get("recognized_columns", []))}`

                **조회 행 수**  
                {row_count_line}
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
if st.session_state.data_loaded:
    hero_badge_class = "hero-badge"
    hero_badge_text = "● CSV 데이터 연결 완료"
else:
    hero_badge_class = "hero-badge hero-badge--offline"
    hero_badge_text = "○ 데이터 미연결"

hero_col, toggle_col = st.columns([5, 1.4], vertical_alignment="center")

with hero_col:
    st.markdown(
        f"""
        <section class="hero">
            <div class="{hero_badge_class}">{hero_badge_text}</div>
            <h1 class="hero-title">써니 데이터 챗봇</h1>
            <p class="hero-description">
                CSV 데이터를 자연어로 검색하고, 조회 결과를 표와 그래프로 확인하세요.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

with toggle_col:
    spec_count = len(st.session_state.specs)
    if st.button(
        f"📋 명세서 {spec_count}" if spec_count else "📋 명세서",
        use_container_width=True,
    ):
        st.session_state.show_spec_panel = not st.session_state.show_spec_panel
        st.rerun()

if st.session_state.show_spec_panel:
    main_col, spec_col = st.columns([2, 1], gap="large")
    with spec_col:
        render_spec_panel()
else:
    main_col = st.container()

# 채팅 입력창은 화면 맨 아래 고정 영역이라 컬럼 밖(최상위)에서 만들어야 한다.
typed_prompt = st.chat_input("업로드한 데이터에 대해 질문해 주세요.")
prompt = st.session_state.pending_prompt or typed_prompt

with main_col:
    if not st.session_state.messages:
        if st.session_state.data_loaded:
            welcome_text = "아래 추천 질문을 누르거나 채팅창에 직접 질문해 보세요."
        else:
            welcome_text = (
                "먼저 왼쪽 사이드바에서 CSV 파일을 업로드해 주세요.<br>"
                "업로드가 끝나면 아래 추천 질문을 누르거나 채팅창에 직접 질문할 수 있어요."
            )

        st.markdown(
            f"""
            <div class="welcome-card">
                <div class="welcome-title">안녕하세요! 써니가 데이터를 찾아드릴게요 ☀️</div>
                <div class="welcome-text">
                    {welcome_text}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 추천 질문은 업로드된 파일의 실제 컬럼에서 만들어진다. 데이터가 없거나
        # 생성에 실패했으면 헛질문을 보여주느니 아예 표시하지 않는다.
        suggestions = st.session_state.suggested_questions
        if st.session_state.data_loaded and suggestions:
            st.markdown(
                '<div class="quick-title">이 데이터로 물어볼 만한 질문</div>',
                unsafe_allow_html=True,
            )
            for column, question in zip(st.columns(len(suggestions)), suggestions):
                with column:
                    if st.button(question, use_container_width=True, key=f"sg_{question}"):
                        st.session_state.pending_prompt = question
                        st.rerun()

    for message in st.session_state.messages:
        avatar = sunny_avatar if message["role"] == "assistant" else "👤"

        if message["role"] == "user" and message.get("id"):
            # "최근 대화"에서 이 질문을 클릭했을 때 스크롤로 찾아올 지점.
            st.markdown(
                f'<div id="chat-anchor-{message["id"]}"></div>',
                unsafe_allow_html=True,
            )

        with st.chat_message(message["role"], avatar=avatar):
            if message["role"] == "assistant":
                render_assistant_message(message)
            else:
                st.markdown(message["content"])

    if prompt:
        st.session_state.pending_prompt = None

        user_message = {
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": prompt,
        }
        st.session_state.messages.append(user_message)

        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=sunny_avatar):
            if not st.session_state.data_loaded:
                st.warning("사이드바에서 CSV 파일을 먼저 업로드해 주세요.")
                st.stop()

            pending = st.session_state.pending_clarification
            spec_saved = None

            # 직전에 답을 보류했다면, 이번 입력은 그 질문에 대한 명확화
            # 답변이다. 명세로 저장한 뒤 원래 질문을 다시 실행한다.
            if pending is not None:
                spec_saved = add_spec(
                    trigger_question=pending["question"],
                    clarification=prompt,
                    ambiguous_reason=pending["reason"],
                )
                st.session_state.specs = load_specs()
                st.session_state.latest_spec_id = spec_saved["id"]
                st.session_state.pending_clarification = None
                st.session_state.show_spec_panel = True
                question_to_run = pending["question"]
            else:
                question_to_run = prompt

            with st.status("질문을 처리하고 있습니다.", expanded=True) as status:
                result = answer_question(
                    st.session_state.con,
                    question_to_run,
                    on_progress=lambda msg: status.write(f"⏳ {msg}"),
                    spec_text=format_specs_for_prompt(st.session_state.specs),
                )

                status.update(
                    label="분석이 완료되었습니다.",
                    state="complete",
                    expanded=False,
                )

            if result.get("is_ambiguous"):
                # 아직 기준을 모르는 질문 — 답하지 않고 되묻는다.
                st.session_state.pending_clarification = {
                    "question": question_to_run,
                    "reason": result["answer"],
                }
                assistant_message = {
                    "role": "assistant",
                    "content": result["answer"],
                    "is_ambiguous": True,
                    "ambiguous_ask": result.get("ambiguous_ask", ""),
                }
            else:
                answer = result["answer"]
                if spec_saved is not None:
                    # 방금 확정한 기준을 실제로 적용했다는 걸 분명히 알려준다.
                    answer = (
                        f"확인했습니다. 앞으로 이 질문은 "
                        f"'{spec_saved['clarification']}' 기준으로 답변할게요. "
                        f"오른쪽 명세서에 추가했습니다.\n\n{answer}"
                    )
                    # 확정된 기준으로 실제 실행된 SQL을 근거로 함께 보관한다.
                    if result.get("sql"):
                        st.session_state.specs = update_spec(
                            spec_saved["id"], resolved_sql=result["sql"]
                        )

                assistant_message = {
                    "role": "assistant",
                    "content": answer,
                    "data": result["data"],
                    "verification": {
                        "table": result["table"],
                        "recognized_columns": result["recognized_columns"],
                        "sql": result["sql"],
                        "validation": result["validation"],
                        "row_count": len(result["data"]),
                        "total_rows": result.get("total_rows", len(result["data"])),
                        "chart": result.get("chart", {}),
                    },
                }

            st.session_state.messages.append(assistant_message)

        # 사이드바("최근 대화")와 명세서 패널은 이 지점보다 위에서 이미 그려졌기
        # 때문에, 방금 추가한 메시지는 지금 화면에 반영되지 않는다. 다시 그려서
        # 대화 목록·명세 개수가 곧바로 최신 상태가 되게 한다.
        st.session_state.scroll_to_bottom = True
        st.rerun()

    # 답변이 새로 추가된 직후에만 맨 아래로 스크롤한다. (탭/펼치기 클릭처럼
    # 새 메시지 없이 다시 그려지는 경우에도 스크롤을 채가면, 위로 올려서
    # 예전 답변을 볼 때마다 화면이 도로 아래로 튕긴다.)
    if st.session_state.scroll_to_bottom:
        st.session_state.scroll_to_bottom = False
        components.html(
            """
            <script>
            (function () {
                const doc = window.parent.document;
                function scrollToBottom() {
                    const el = doc.querySelector('.block-container');
                    if (el) el.scrollTop = el.scrollHeight;
                }
                scrollToBottom();
                // 이미지/폰트 등으로 레이아웃이 뒤늦게 자리잡는 경우를 대비해
                // 한 번 더 시도한다. (계속 지켜보는 옵저버는 두지 않는다.)
                setTimeout(scrollToBottom, 150);
            })();
            </script>
            """,
            height=0,
        )

    # 사이드바 "최근 대화"에서 특정 질문을 클릭했을 때, 그 질문이 있는
    # 위치로 스크롤한다. (부모 문서를 iframe 너머로 조작하는 상황이라
    # 'smooth' 애니메이션은 신뢰할 수 없어 즉시 이동시킨다 — 아래
    # scroll-to-bottom과 동일한 방식)
    if st.session_state.scroll_to_message_id:
        target_id = st.session_state.scroll_to_message_id
        st.session_state.scroll_to_message_id = None
        components.html(
            f"""
            <script>
            (function () {{
                const doc = window.parent.document;
                function scrollToAnchor() {{
                    const el = doc.getElementById('chat-anchor-{target_id}');
                    const container = doc.querySelector('.block-container');
                    if (el && container) el.scrollIntoView({{behavior: 'auto', block: 'start'}});
                }}
                // 데이터 표/차트/탭처럼 뒤늦게 자리를 잡는 요소가 있으면 그
                // 레이아웃 변화가 스크롤 위치를 다시 밀어내므로, 짧은 간격으로
                // 여러 번 재조준한다. (마지막 시도가 최종 위치를 확정)
                [0, 150, 400, 900, 1500].forEach((delay) => {{
                    setTimeout(scrollToAnchor, delay);
                }});
            }})();
            </script>
            """,
            height=0,
        )
