from __future__ import annotations

import html
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from PIL import Image


# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env", override=True)

from agent.claude_client import (  # noqa: E402
    AgentConfigurationError,
    ClaudeAPIError,
    choose_default_model,
    get_configured_models,
    list_available_models,
)
from agent.workflow import DataAgentError, run_data_agent  # noqa: E402
from backend.data_engine import DuckDBEngine  # noqa: E402

AVATAR_PATH = BASE_DIR / "assets" / "sunny_avatar.png"

st.set_page_config(
    page_title="SUNNY 9조 데이터 챗봇",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

sunny_avatar = Image.open(AVATAR_PATH)


# ---------------------------------------------------------
# 디자인
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    :root {
        --sunny-red: #ef3b32;
        --sunny-blue: #39a9db;
        --sunny-navy: #163f56;
        --border: rgba(255, 255, 255, 0.90);
    }

    #MainMenu, footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent; }

    .stApp {
        background-image:
            radial-gradient(circle at 12% 18%, rgba(121, 211, 244, 0.30), transparent 34%),
            radial-gradient(circle at 88% 14%, rgba(255, 226, 126, 0.24), transparent 30%),
            linear-gradient(145deg, #eefbff 0%, #dff5ff 48%, #fff8df 100%);
        background-size: cover;
        background-attachment: fixed;
    }

    [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        background: transparent;
    }

    .block-container {
        max-width: 1020px;
        min-height: calc(100vh - 38px);
        margin-top: 14px;
        margin-bottom: 18px;
        padding: 1.3rem 2.1rem 7.2rem 2.1rem;
        border: 1px solid var(--border);
        border-radius: 26px;
        background: rgba(255, 255, 255, 0.80);
        backdrop-filter: blur(22px);
        -webkit-backdrop-filter: blur(22px);
        box-shadow: 0 24px 70px rgba(27, 91, 123, 0.18);
    }

    [data-testid="stSidebar"] {
        background: rgba(255, 255, 255, 0.82);
        backdrop-filter: blur(22px);
        -webkit-backdrop-filter: blur(22px);
        border-right: 1px solid rgba(255, 255, 255, 0.90);
        box-shadow: 10px 0 34px rgba(31, 92, 122, 0.12);
    }

    [data-testid="stSidebarContent"] { padding-top: 1.1rem; }

    .brand-kicker {
        margin: 0 0 2px 0;
        color: var(--sunny-red);
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.10em;
    }

    .brand-title {
        margin: 0;
        color: var(--sunny-navy);
        font-size: 21px;
        line-height: 1.15;
        font-weight: 900;
    }

    .brand-subtitle {
        margin: 4px 0 0 0;
        color: #6e8794;
        font-size: 12px;
    }

    .hero {
        padding: 2px 2px 15px 2px;
        border-bottom: 1px solid rgba(84, 145, 173, 0.14);
        margin-bottom: 0.8rem;
    }

    .hero-badge {
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        border-radius: 999px;
        color: #167ca4;
        background: rgba(225, 247, 255, 0.88);
        border: 1px solid rgba(87, 184, 220, 0.24);
        font-size: 12px;
        font-weight: 750;
        margin-bottom: 8px;
    }

    .hero-title {
        margin: 0;
        color: var(--sunny-navy);
        font-size: 29px;
        font-weight: 900;
        letter-spacing: -0.04em;
    }

    .hero-description {
        margin: 6px 0 0 0;
        color: #668493;
        font-size: 14px;
        line-height: 1.6;
    }

    .welcome-card {
        margin: 12px 0 18px 0;
        padding: 24px 22px;
        text-align: center;
        border-radius: 22px;
        background: rgba(255, 255, 255, 0.76);
        border: 1px solid rgba(255, 255, 255, 0.92);
        box-shadow: 0 12px 36px rgba(30, 102, 138, 0.08);
    }

    .welcome-title {
        color: #1d536e;
        font-size: 19px;
        font-weight: 850;
        margin-bottom: 6px;
    }

    .welcome-text {
        color: #708b98;
        font-size: 13px;
        line-height: 1.7;
    }

    .data-card {
        margin-top: 8px;
        padding: 13px 14px;
        border-radius: 15px;
        background: rgba(255, 255, 255, 0.82);
        border: 1px solid rgba(113, 170, 197, 0.18);
        box-shadow: 0 8px 22px rgba(32, 93, 124, 0.07);
    }

    .status-line {
        display: flex;
        align-items: center;
        gap: 8px;
        color: #28576c;
        font-size: 13px;
        font-weight: 780;
    }

    .status-dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #25b96f;
        box-shadow: 0 0 0 4px rgba(37, 185, 111, 0.12);
    }

    .status-dot.off {
        background: #a9b5bb;
        box-shadow: 0 0 0 4px rgba(169, 181, 187, 0.14);
    }

    .data-meta {
        margin-top: 8px;
        color: #79909b;
        font-size: 11px;
        line-height: 1.65;
        word-break: break-word;
    }

    [data-testid="stChatMessage"] {
        margin-bottom: 0.7rem;
        padding: 0.95rem 1.02rem;
        border: 1px solid rgba(181, 216, 231, 0.60);
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 9px 26px rgba(35, 94, 124, 0.07);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
    }

    [data-testid="stChatMessageAvatarAssistant"] img,
    [data-testid="stChatMessageAvatarUser"] img {
        border: 2px solid white;
        box-shadow: 0 4px 14px rgba(31, 86, 113, 0.16);
    }

    [data-testid="stChatInput"] {
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.98);
        border: 1px solid rgba(139, 190, 213, 0.55);
        box-shadow: 0 12px 34px rgba(26, 86, 115, 0.16);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
    }

    [data-testid="stDataFrame"] {
        border: 1px solid rgba(130, 181, 204, 0.28);
        border-radius: 14px;
        overflow: hidden;
    }

    details { border-radius: 14px !important; }

    .stButton > button {
        width: 100%;
        min-height: 42px;
        border: 1px solid rgba(112, 170, 196, 0.30);
        border-radius: 13px;
        background: rgba(255, 255, 255, 0.86);
        color: #24566e;
        font-weight: 750;
        transition: all 0.16s ease;
    }

    .stButton > button:hover {
        color: var(--sunny-red);
        border-color: rgba(239, 59, 50, 0.42);
        transform: translateY(-1px);
        box-shadow: 0 7px 20px rgba(239, 59, 50, 0.10);
    }

    .quick-title {
        margin: 4px 0 8px 2px;
        color: #718b98;
        font-size: 12px;
        font-weight: 750;
    }

    /* 출처 사이드 드로어 */
    .sunny-drawer-overlay {
        position: fixed;
        inset: 0;
        background: rgba(15, 40, 54, 0.35);
        z-index: 9998;
        animation: sunnyDrawerFade 0.18s ease;
    }

    .sunny-drawer-panel {
        position: fixed;
        top: 0;
        right: 0;
        height: 100vh;
        width: min(380px, 92vw);
        background: #f5f7f9;
        border-left: 1px solid rgba(113, 170, 197, 0.25);
        box-shadow: -14px 0 40px rgba(27, 91, 123, 0.20);
        z-index: 9999;
        padding: 64px 20px 24px 20px;
        overflow-y: auto;
        animation: sunnyDrawerSlideIn 0.30s cubic-bezier(0.16, 0.84, 0.44, 1);
    }

    @keyframes sunnyDrawerSlideIn {
        from { transform: translateX(100%); }
        to { transform: translateX(0); }
    }

    @keyframes sunnyDrawerFade {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    .drawer-header {
        display: flex;
        align-items: center;
        margin-bottom: 16px;
    }

    .drawer-title {
        font-size: 16px;
        font-weight: 850;
        color: var(--sunny-navy);
    }

    .drawer-section {
        background: rgba(255, 255, 255, 0.88);
        border: 1px solid rgba(113, 170, 197, 0.18);
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 10px;
        box-shadow: 0 6px 16px rgba(32, 93, 124, 0.05);
    }

    .drawer-label {
        font-size: 11px;
        font-weight: 750;
        color: #79909b;
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .drawer-value {
        display: inline-block;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 12.5px;
        color: #1d536e;
        font-weight: 650;
        background: rgba(22, 63, 86, 0.07);
        border: 1px solid rgba(113, 170, 197, 0.22);
        border-radius: 7px;
        padding: 4px 9px;
        word-break: break-word;
        white-space: pre-wrap;
    }

    .drawer-code {
        margin: 0;
        padding: 12px 13px;
        border-radius: 10px;
        background: var(--sunny-navy);
        color: #d9f1ff;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 12px;
        line-height: 1.55;
        white-space: pre-wrap;
        word-break: break-word;
        overflow-x: auto;
    }

    /* 결과 카드 커스텀 탭 바 (데이터 표 / 시각화 + 출처) */
    div[class*="st-key-sunny_tab_"] button {
        width: auto !important;
        min-height: 34px !important;
        padding: 6px 4px 9px 4px !important;
        border: none !important;
        border-bottom: 3px solid transparent !important;
        border-radius: 0 !important;
        background: transparent !important;
        color: #7c94a0 !important;
        font-weight: 700 !important;
        box-shadow: none !important;
        transform: none !important;
    }

    div[class*="st-key-sunny_tab_"] button:hover {
        color: var(--sunny-red) !important;
        border-bottom-color: rgba(239, 59, 50, 0.28) !important;
        transform: none !important;
        box-shadow: none !important;
    }

    div[class*="st-key-sunny_source_"] {
        display: flex !important;
        justify-content: flex-end !important;
    }

    div[class*="st-key-sunny_source_"] button {
        width: auto !important;
        min-height: 34px !important;
        padding: 6px 12px !important;
        border: 1px solid rgba(113, 170, 197, 0.30) !important;
        border-radius: 999px !important;
        background: rgba(255, 255, 255, 0.70) !important;
        color: #7c94a0 !important;
        font-weight: 700 !important;
        font-size: 13px !important;
        box-shadow: none !important;
        transform: none !important;
    }

    div[class*="st-key-sunny_source_"] button:hover {
        color: var(--sunny-red) !important;
        border-color: rgba(239, 59, 50, 0.42) !important;
    }

    .sunny-tabbar-rule {
        margin: -6px 0 10px 0;
        border-bottom: 1px solid rgba(84, 145, 173, 0.16);
    }

    @media (max-width: 768px) {
        .block-container {
            margin: 0;
            padding: 1rem 0.8rem 7rem 0.8rem;
            border-radius: 0;
            min-height: 100vh;
        }
        .hero-title { font-size: 24px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# st.markdown(unsafe_allow_html=True)로 넣은 onclick 등 인라인 이벤트 속성은
# Streamlit이 보안상 제거하므로, 실제 <script>가 실행되는 components.html로
# "출처" 드로어의 바깥 영역 클릭 · ESC 키 감지를 연결합니다.
# components.html의 iframe은 Streamlit이 리런될 때마다 새로 만들어지고 이전
# iframe(과 거기서 정의된 클로저)은 즉시 죽어버리므로, "한 번만 등록" 방식은
# 리스너가 재부착되지 않는 문제가 있습니다. 매 리런마다 이전 핸들러를 제거하고
# 현재 살아있는 iframe에서 새 핸들러를 등록합니다.
components.html(
    """
    <script>
    (function () {
        const doc = window.parent.document;
        if (doc.__sunnyDrawerClickHandler) {
            doc.removeEventListener("click", doc.__sunnyDrawerClickHandler, true);
        }
        if (doc.__sunnyDrawerKeyHandler) {
            doc.removeEventListener("keydown", doc.__sunnyDrawerKeyHandler, true);
        }
        function closeOpenDrawer() {
            const overlay = doc.querySelector(".sunny-drawer-overlay");
            if (!overlay) { return; }
            const idx = overlay.getAttribute("data-idx");
            if (idx === null) { return; }
            const closeButton = doc.querySelector(".st-key-close_drawer_" + idx + " button");
            if (closeButton) { closeButton.click(); }
        }
        const clickHandler = function (event) {
            const panel = doc.querySelector(".sunny-drawer-panel");
            if (!panel || panel.contains(event.target)) { return; }
            closeOpenDrawer();
        };
        const keyHandler = function (event) {
            if (event.key !== "Escape") { return; }
            closeOpenDrawer();
        };
        doc.__sunnyDrawerClickHandler = clickHandler;
        doc.__sunnyDrawerKeyHandler = keyHandler;
        doc.addEventListener("click", clickHandler, true);
        doc.addEventListener("keydown", keyHandler, true);
    })();
    </script>
    """,
    height=0,
)


# ---------------------------------------------------------
# 상태 관리
# ---------------------------------------------------------
def _init_state(name: str, value: Any) -> None:
    if name not in st.session_state:
        st.session_state[name] = value


_init_state("messages", [])
_init_state("pending_prompt", None)
_init_state("dataset_path", None)
_init_state("dataset_source", None)
_init_state("dataset_original_name", None)
_init_state("available_models", [])
_init_state("model_catalog_error", None)
_init_state("model_catalog_loaded", False)
_init_state("primary_model_widget", None)
_init_state("fallback_models_widget", [])


def reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pending_prompt = None
    for key in [
        k
        for k in st.session_state
        if k.startswith("drawer_open_") or k.startswith("active_tab_")
    ]:
        del st.session_state[key]


def disconnect_dataset() -> None:
    st.session_state.dataset_path = None
    st.session_state.dataset_source = None
    st.session_state.dataset_original_name = None
    reset_chat()


def resolve_current_dataset() -> Path | None:
    stored_path = st.session_state.dataset_path
    if not stored_path:
        return None
    candidate = Path(stored_path)
    if candidate.is_file() and candidate.suffix.lower() == ".parquet":
        return candidate.resolve()
    disconnect_dataset()
    return None


def refresh_model_catalog() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    st.session_state.model_catalog_loaded = True
    try:
        models = list_available_models(limit=100)
        st.session_state.available_models = models
        st.session_state.model_catalog_error = None
    except (AgentConfigurationError, ClaudeAPIError) as exc:
        st.session_state.available_models = []
        st.session_state.model_catalog_error = str(exc)


def prepare_uploaded_dataset(uploaded_file, on_progress=None) -> Path:
    """업로드 파일을 로컬에 저장하고 CSV라면 Parquet로 변환합니다."""
    upload_root = PROJECT_ROOT / "data" / "user_uploads"
    upload_root.mkdir(parents=True, exist_ok=True)

    safe_name = Path(uploaded_file.name).name
    extension = Path(safe_name).suffix.lower()
    if extension not in {".csv", ".parquet"}:
        raise ValueError("CSV 또는 Parquet 파일만 업로드할 수 있습니다.")

    upload_id = uuid.uuid4().hex[:12]
    raw_path = upload_root / f"{upload_id}_{safe_name}"

    if on_progress:
        on_progress("upload_saving", f"업로드 파일을 저장하고 있습니다: {safe_name}", {})

    uploaded_file.seek(0)
    with raw_path.open("wb") as output:
        while True:
            chunk = uploaded_file.read(8 * 1024 * 1024)
            if not chunk:
                break
            output.write(chunk)

    if extension == ".parquet":
        if on_progress:
            on_progress("upload_ready", "Parquet 업로드를 완료했습니다.", {"path": str(raw_path)})
        return raw_path.resolve()

    parquet_path = upload_root / f"{upload_id}_{Path(safe_name).stem}.parquet"
    if on_progress:
        on_progress("csv_reading", "CSV 구조를 확인하고 있습니다.", {})
        on_progress("parquet_converting", "CSV를 분석용 Parquet로 변환하고 있습니다.", {})

    pl.scan_csv(str(raw_path), infer_schema_length=10000).sink_parquet(
        str(parquet_path),
        compression="zstd",
    )

    try:
        raw_path.unlink()
    except OSError:
        pass

    if on_progress:
        on_progress("upload_ready", "CSV 업로드와 Parquet 변환을 완료했습니다.", {"path": str(parquet_path)})
    return parquet_path.resolve()


def compact_step(event: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "columns",
        "model",
        "attempted_models",
        "route",
        "reason",
        "sql",
        "code",
        "metrics",
        "error",
        "row_count",
        "status_code",
        "chart",
        "note",
    }
    compact_details: dict[str, Any] = {}
    for key in allowed_keys:
        if key not in details:
            continue
        value = details[key]
        if isinstance(value, str) and len(value) > 3000:
            value = value[:3000] + "…"
        compact_details[key] = value
    return {"event": event, "message": message, "details": compact_details}


# API 키가 있으면 최초 한 번 자동으로 실제 모델 목록을 조회합니다.
if not st.session_state.model_catalog_loaded and os.getenv("ANTHROPIC_API_KEY", "").strip():
    refresh_model_catalog()

current_dataset = resolve_current_dataset()


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

    st.markdown("##### Claude 모델")
    api_key_exists = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    if st.button("사용 가능한 모델 새로고침", use_container_width=True):
        refresh_model_catalog()
        st.rerun()

    available_models: list[dict[str, Any]] = st.session_state.available_models
    available_ids = [str(model["id"]) for model in available_models]
    display_by_id = {
        str(model["id"]): f"{model.get('display_name') or model['id']} · {model['id']}"
        for model in available_models
    }

    model_candidates: list[str] = []
    if available_ids:
        configured_models = get_configured_models()
        default_model = choose_default_model(available_ids, configured_models)
        if st.session_state.primary_model_widget not in available_ids:
            st.session_state.primary_model_widget = default_model

        primary_model = st.selectbox(
            "기본 모델",
            options=available_ids,
            key="primary_model_widget",
            format_func=lambda model_id: display_by_id.get(model_id, model_id),
            help="현재 API 키로 실제 조회된 모델만 표시합니다.",
        )

        fallback_options = [model for model in available_ids if model != primary_model]
        valid_fallbacks = [
            model
            for model in st.session_state.fallback_models_widget
            if model in fallback_options
        ]
        if valid_fallbacks != st.session_state.fallback_models_widget:
            st.session_state.fallback_models_widget = valid_fallbacks

        fallback_models = st.multiselect(
            "오류 시 대체 모델",
            options=fallback_options,
            key="fallback_models_widget",
            format_func=lambda model_id: display_by_id.get(model_id, model_id),
            help="기본 모델이 403·404·일시 오류로 실패하면 위에서 선택한 순서대로 시도합니다.",
        )
        model_candidates = [primary_model, *fallback_models]
        st.caption(f"사용 후보 {len(model_candidates)}개 · 기본: {primary_model}")
    else:
        catalog_error = st.session_state.model_catalog_error
        if not api_key_exists:
            st.warning(".env에 ANTHROPIC_API_KEY를 입력한 뒤 모델 목록을 새로고침해 주세요.")
        elif catalog_error:
            st.warning(catalog_error)

        configured = get_configured_models()
        manual_value = ",".join(configured)
        manual_models = st.text_input(
            "모델 ID 직접 입력",
            value=manual_value,
            placeholder="예: claude-sonnet-…",
            help="모델 목록 조회가 실패한 경우에만 사용하는 임시 입력입니다. 여러 개는 쉼표로 구분합니다.",
        )
        model_candidates = [
            model.strip() for model in manual_models.split(",") if model.strip()
        ]

    st.markdown("---")
    st.markdown("##### 데이터 업로드")
    uploaded_file = st.file_uploader(
        "CSV 또는 Parquet 파일",
        type=["csv", "parquet"],
        help="현재 UI 업로더는 기능 확인용입니다. 10~20GB 파일은 추후 청크 업로드 서버와 연결합니다.",
        key="dataset_uploader",
    )

    if st.button(
        "업로드한 데이터 적용",
        use_container_width=True,
        disabled=uploaded_file is None,
    ):
        try:
            upload_line = st.empty()

            def show_upload_progress(event: str, message: str, details: dict[str, Any]) -> None:
                icons = {
                    "upload_saving": "📤",
                    "csv_reading": "📖",
                    "parquet_converting": "📦",
                    "upload_ready": "✅",
                }
                upload_line.info(f"{icons.get(event, '⏳')} {message}")

            selected_path = prepare_uploaded_dataset(
                uploaded_file,
                on_progress=show_upload_progress,
            )
            upload_line.success("✅ 업로드 데이터 준비 완료")
            st.session_state.dataset_path = str(selected_path)
            st.session_state.dataset_source = "uploaded"
            st.session_state.dataset_original_name = uploaded_file.name
            reset_chat()
            st.rerun()
        except Exception as exc:
            st.error(f"데이터 준비에 실패했습니다: {exc}")

    if st.session_state.dataset_path and st.button("데이터 연결 해제", use_container_width=True):
        disconnect_dataset()
        st.rerun()

    st.markdown("---")
    st.markdown("##### 데이터 상태")

    if current_dataset is None:
        dataset_status = "업로드된 데이터 없음"
        dataset_meta = "실제 CSV 또는 Parquet 파일을 업로드해야 채팅이 활성화됩니다."
        dot_class = "status-dot off"
    else:
        dataset_status = "실제 업로드 데이터 준비 완료"
        original_name = st.session_state.dataset_original_name or current_dataset.name
        dataset_meta = (
            f"업로드 파일: {original_name}<br>"
            f"분석 파일: {current_dataset.name}<br>"
            "분석 방식: Agent 계획 → DuckDB SQL → 제한된 Python 분석 → Plotly"
        )
        dot_class = "status-dot"

    st.markdown(
        f"""
        <div class="data-card">
            <div class="status-line">
                <span class="{dot_class}"></span>
                {dataset_status}
            </div>
            <div class="data-meta">{dataset_meta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("##### 최근 대화")
    user_messages = [
        message["content"]
        for message in st.session_state.messages
        if message.get("role") == "user"
    ]
    if user_messages:
        for title in reversed(user_messages[-5:]):
            st.caption(f"• {title[:26]}")
    else:
        st.caption("아직 대화 기록이 없습니다.")

    st.markdown("---")
    st.caption("SUNNY 9조 · Hybrid SQL/Python Agent v6.1 Team Test")


# ---------------------------------------------------------
# 결과 렌더링
# ---------------------------------------------------------
def _format_metric_value(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(numeric):
        return "-"
    if numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.4f}".rstrip("0").rstrip(".")


def render_chart(
    df: pd.DataFrame,
    chart: dict[str, Any],
    chart_note: str = "",
) -> None:
    chart_type = str(chart.get("type", "none")).lower().strip()
    x_column = str(chart.get("x", "")).strip()
    y_column = str(chart.get("y", "")).strip()
    title = str(chart.get("title", "")).strip()

    if chart_type == "metric":
        metrics = chart.get("metrics", [])
        if not isinstance(metrics, list) or not metrics:
            st.info("표시할 단일 지표가 없습니다.")
            return
        columns = st.columns(min(len(metrics), 4))
        for container, metric in zip(columns, metrics):
            if not isinstance(metric, dict):
                continue
            container.metric(
                str(metric.get("label", "값")),
                _format_metric_value(metric.get("value")),
            )
        if chart_note:
            st.caption(chart_note)
        return

    if chart_type == "none" or df.empty:
        reason = str(chart.get("reason", "")).strip()
        st.info(reason or "이 결과에는 표시할 그래프가 없습니다.")
        if chart_note:
            st.caption(chart_note)
        return

    prepared = df.copy()
    required_columns = [column for column in (x_column, y_column) if column]
    missing = [column for column in required_columns if column not in prepared.columns]
    if missing:
        st.warning("시각화 컬럼을 찾지 못했습니다: " + ", ".join(missing))
        return

    try:
        if chart_type in {"bar", "line", "pie", "scatter"} and y_column:
            prepared[y_column] = pd.to_numeric(
                prepared[y_column].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
            prepared = prepared.dropna(subset=[y_column])

        if chart_type == "scatter" and x_column:
            prepared[x_column] = pd.to_numeric(
                prepared[x_column].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
            prepared = prepared.dropna(subset=[x_column, y_column])

        if chart_type == "line" and x_column:
            x_name = x_column.casefold()
            date_hint = any(
                token in x_name
                for token in ("date", "time", "datetime", "timestamp", "날짜", "일자", "시간")
            )
            if date_hint or pd.api.types.is_datetime64_any_dtype(prepared[x_column]):
                converted_dates = pd.to_datetime(prepared[x_column], errors="coerce")
                if converted_dates.notna().sum() >= max(1, int(len(prepared) * 0.6)):
                    prepared[x_column] = converted_dates
            prepared = prepared.dropna(subset=[x_column]).sort_values(x_column)

        if prepared.empty:
            st.info("유효한 숫자 또는 날짜 값이 없어 그래프를 표시하지 않았습니다.")
            return

        if chart_type == "line":
            figure = px.line(
                prepared,
                x=x_column,
                y=y_column,
                markers=len(prepared) <= 200,
                title=title or None,
            )
        elif chart_type == "pie":
            positive = prepared[prepared[y_column] > 0].copy()
            if positive.empty:
                st.info("원그래프에 사용할 양수 값이 없습니다.")
                return
            figure = px.pie(
                positive,
                names=x_column,
                values=y_column,
                title=title or None,
                hole=0.28,
            )
        elif chart_type == "scatter":
            figure = px.scatter(
                prepared,
                x=x_column,
                y=y_column,
                title=title or None,
                opacity=0.7,
            )
        elif chart_type == "histogram":
            prepared[x_column] = pd.to_numeric(
                prepared[x_column].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
            prepared = prepared.dropna(subset=[x_column])
            figure = px.histogram(
                prepared,
                x=x_column,
                nbins=min(60, max(10, int(len(prepared) ** 0.5))),
                title=title or None,
            )
        elif chart_type == "box":
            prepared[y_column] = pd.to_numeric(
                prepared[y_column].astype("string").str.replace(",", "", regex=False),
                errors="coerce",
            )
            prepared = prepared.dropna(subset=[y_column])
            figure = px.box(
                prepared,
                y=y_column,
                points="outliers",
                title=title or None,
            )
        else:
            orientation = str(chart.get("orientation", "v")).lower()
            if orientation == "h":
                figure = px.bar(
                    prepared.sort_values(y_column, ascending=True),
                    x=y_column,
                    y=x_column,
                    orientation="h",
                    text_auto=True,
                    title=title or None,
                )
                figure.update_yaxes(categoryorder="total ascending")
            else:
                figure = px.bar(
                    prepared,
                    x=x_column,
                    y=y_column,
                    text_auto=True,
                    title=title or None,
                )
    except Exception as exc:
        st.warning(f"시각화를 만들지 못했습니다: {exc}")
        return

    figure.update_layout(
        margin=dict(l=12, r=12, t=48 if title else 22, b=18),
        height=420 if chart_type in {"bar", "line", "scatter"} else 380,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.55)",
        font=dict(size=13),
        hovermode="closest",
    )
    figure.update_xaxes(automargin=True)
    figure.update_yaxes(automargin=True)
    st.plotly_chart(
        figure,
        use_container_width=True,
        config={
            "displayModeBar": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            "toImageButtonOptions": {"format": "png", "filename": "sunny_analysis_chart", "scale": 2},
        },
    )
    if chart_note:
        st.caption(chart_note)


def render_execution_details(
    steps: list[dict[str, Any]],
    verification: dict[str, Any] | None = None,
    error_detail: str | None = None,
) -> None:
    with st.expander("상세 실행 과정 보기", expanded=False):
        for index, step in enumerate(steps, start=1):
            st.markdown(f"**{index}. {step.get('message', '')}**")
            details = step.get("details", {})
            if details.get("columns"):
                st.caption("컬럼: " + ", ".join(map(str, details["columns"])))
            if details.get("model"):
                st.caption("모델: " + str(details["model"]))
            if details.get("attempted_models"):
                st.caption("시도한 모델: " + " → ".join(map(str, details["attempted_models"])))
            if details.get("reason"):
                st.caption("선택 이유: " + str(details["reason"]))
            if details.get("chart"):
                st.caption("시각화 설정: " + str(details["chart"]))
            if details.get("note"):
                st.caption("시각화 참고: " + str(details["note"]))
            if details.get("sql"):
                st.code(details["sql"], language="sql")
            if details.get("code"):
                st.code(details["code"], language="python")
            if details.get("metrics"):
                st.json(details["metrics"])
            if details.get("error"):
                st.caption("오류: " + str(details["error"]))

        if verification:
            st.markdown("---")
            st.caption(verification.get("validation", "검증 상태를 확인할 수 없습니다."))
            sql = verification.get("sql")
            if sql:
                st.markdown("**최종 DuckDB SQL**")
                st.code(sql, language="sql")
            python_code = verification.get("python_code", "")
            if python_code:
                st.markdown("**실제로 수행한 제한된 Python 분석 코드**")
                st.code(python_code, language="python")
            metrics = verification.get("python_metrics", {})
            if metrics:
                st.markdown("**Python 분석 지표**")
                st.json(metrics)
            note = verification.get("python_note", "")
            if note:
                st.caption(note)

        if error_detail:
            st.markdown("---")
            st.caption(error_detail)


def normalize_answer_text(text: str) -> str:
    """숫자 범위의 물결표가 Markdown/폰트에서 흐리게 보이는 문제를 방지합니다."""
    return re.sub(r"(?<=[0-9%℃°])\s*~\s*(?=[0-9+-])", "–", text)


def render_sources_drawer(idx: int, verification: dict[str, Any], row_count_fallback: int) -> None:
    """탭 바의 '출처' 항목을 눌렀을 때 오른쪽에서 슬라이드인되는 오버레이 드로어."""
    recognized = verification.get("recognized_columns", [])
    attempted_models = verification.get("attempted_models", [])

    model = html.escape(str(verification.get("model", "확인되지 않음")))
    tool = html.escape(str(verification.get("tool", "확인되지 않음")))
    route = html.escape(str(verification.get("route", "확인되지 않음")))
    columns_text = html.escape(", ".join(map(str, recognized)) or "없음")
    row_count = html.escape(str(verification.get("row_count", row_count_fallback)))

    fallback_section = ""
    if len(attempted_models) > 1:
        fallback_text = html.escape(" → ".join(map(str, attempted_models)))
        fallback_section = f"""
            <div class="drawer-section">
                <div class="drawer-label">모델 대체 경로</div>
                <div class="drawer-value">{fallback_text}</div>
            </div>
        """

    sql = str(verification.get("sql", "")).strip()
    sql_section = ""
    if sql:
        sql_section = f"""
            <div class="drawer-section">
                <div class="drawer-label">실행된 SQL 쿼리</div>
                <pre class="drawer-code">{html.escape(sql)}</pre>
            </div>
        """

    close_key = f"close_drawer_{idx}"

    st.markdown(
        f"""
        <div class="sunny-drawer-overlay" data-idx="{idx}"></div>
        <div class="sunny-drawer-panel">
            <div class="drawer-header">
                <span class="drawer-title">🔗 출처</span>
            </div>
            <div class="drawer-section">
                <div class="drawer-label">사용 모델</div>
                <div class="drawer-value">{model}</div>
            </div>
            <div class="drawer-section">
                <div class="drawer-label">선택한 분석 도구</div>
                <div class="drawer-value">{tool}</div>
            </div>
            <div class="drawer-section">
                <div class="drawer-label">실행 경로</div>
                <div class="drawer-value">{route}</div>
            </div>
            <div class="drawer-section">
                <div class="drawer-label">인식한 컬럼</div>
                <div class="drawer-value">{columns_text}</div>
            </div>
            <div class="drawer-section">
                <div class="drawer-label">최종 표시 행 수</div>
                <div class="drawer-value">{row_count}개</div>
            </div>
            {fallback_section}
            {sql_section}
        </div>
        <style>
        .st-key-{close_key} {{
            position: fixed;
            top: 14px;
            right: 14px;
            z-index: 10001;
            width: 34px;
        }}
        .st-key-{close_key} button {{
            width: 34px;
            height: 34px;
            min-height: 34px;
            padding: 0;
            border-radius: 50%;
            background: #ffffff;
            color: var(--sunny-red);
            border: 1px solid rgba(239, 59, 50, 0.35);
            font-weight: 800;
            box-shadow: 0 6px 16px rgba(27, 91, 123, 0.18);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    if st.button("✕", key=close_key):
        st.session_state[f"drawer_open_{idx}"] = False
        st.rerun()


def render_result_tabbar(idx: int, active_tab: str, drawer_open: bool) -> None:
    """'데이터 표 | 시각화' 탭과, 탭 전환 없이 드로어만 여는 '출처' 항목을 한 줄에 렌더링합니다."""
    tab_items = [("table", "데이터 표"), ("chart", "시각화")]

    style_rules = [
        f".st-key-sunny_tab_{tab_id}_{idx} button {{"
        " color: var(--sunny-navy) !important;"
        " border-bottom: 3px solid var(--sunny-red) !important;"
        " }"
        for tab_id, _ in tab_items
        if tab_id == active_tab
    ]
    if drawer_open:
        style_rules.append(
            f".st-key-sunny_source_{idx} button {{"
            " color: var(--sunny-red) !important;"
            " background: rgba(239, 59, 50, 0.10) !important;"
            " border-color: rgba(239, 59, 50, 0.35) !important;"
            " }"
        )
    st.markdown(f"<style>{' '.join(style_rules)}</style>", unsafe_allow_html=True)

    col_table, col_chart, col_source = st.columns([0.18, 0.18, 0.64])
    columns = {"table": col_table, "chart": col_chart}
    for tab_id, label in tab_items:
        with columns[tab_id]:
            if st.button(label, key=f"sunny_tab_{tab_id}_{idx}"):
                st.session_state[f"active_tab_{idx}"] = tab_id
                st.rerun()

    with col_source:
        if st.button("🔗 출처", key=f"sunny_source_{idx}"):
            st.session_state[f"drawer_open_{idx}"] = not drawer_open
            st.rerun()

    st.markdown('<div class="sunny-tabbar-rule"></div>', unsafe_allow_html=True)


def render_assistant_message(message: dict[str, Any], idx: int) -> None:
    success = bool(message.get("success", True))
    content = normalize_answer_text(str(message.get("content", "")))
    steps = list(message.get("steps", []))

    if not success:
        st.error(content)
        render_execution_details(
            steps,
            error_detail=message.get("error_detail"),
        )
        return

    st.markdown(content)
    verification = dict(message.get("verification", {}))
    data = message.get("data")
    df = pd.DataFrame(data or [])

    active_tab_key = f"active_tab_{idx}"
    drawer_key = f"drawer_open_{idx}"
    _init_state(active_tab_key, "table")
    _init_state(drawer_key, False)

    active_tab = st.session_state[active_tab_key]
    drawer_open = st.session_state[drawer_key]

    render_result_tabbar(idx, active_tab, drawer_open)

    if active_tab == "table":
        if df.empty:
            st.info("조건에 맞는 데이터 행이 없습니다.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
    elif active_tab == "chart":
        chart_data = verification.get("chart_data")
        chart_df = pd.DataFrame(chart_data) if chart_data is not None else df
        render_chart(
            chart_df,
            verification.get("chart", {}),
            str(verification.get("chart_note", "")),
        )

    if drawer_open:
        render_sources_drawer(idx, verification, len(df))


def dataset_suggestions(dataset: Path | None) -> list[str]:
    if dataset is None:
        return []
    try:
        schema = DuckDBEngine(dataset).get_schema()
    except Exception:
        return ["전체 데이터 건수를 알려줘"]

    names = [str(column["name"]) for column in schema]
    numeric_types = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "BIGINT", "SMALLINT")
    numeric = [
        str(column["name"])
        for column in schema
        if any(token in str(column["type"]).upper() for token in numeric_types)
    ]

    suggestions = ["전체 데이터 건수를 알려줘"]
    if names:
        suggestions.append(f"{names[0]} 값별 데이터 건수 상위 10개를 보여줘")
    if numeric:
        suggestions.append(f"{numeric[0]}의 분포와 이상치를 분석해줘")
    return suggestions[:3]


# ---------------------------------------------------------
# 메인 화면
# ---------------------------------------------------------
dataset_ready = current_dataset is not None
model_ready = bool(model_candidates)
chat_ready = dataset_ready and model_ready

if dataset_ready and model_ready:
    hero_badge = "● 데이터와 Claude 모델 연결 완료"
elif dataset_ready:
    hero_badge = "● Claude 모델 선택 필요"
else:
    hero_badge = "● 데이터 업로드 필요"

st.markdown(
    f"""
    <section class="hero">
        <div class="hero-badge">{hero_badge}</div>
        <h1 class="hero-title">SUNNY 데이터 챗봇</h1>
        <p class="hero-description">
            품질 데이터를 자연어로 검색하고, DuckDB·Python 분석 결과를 표와 그래프로 확인하세요.
        </p>
    </section>
    """,
    unsafe_allow_html=True,
)

# 대화 영역만 별도로 스크롤되고 입력창은 st.bottom에 고정됩니다.
chat_area = st.container(height=610, border=False)

with chat_area:
    if not st.session_state.messages:
        st.markdown(
            """
            <div class="welcome-card">
                <div class="welcome-title">안녕하세요! 써니가 데이터를 찾아드릴게요 ☀️</div>
                <div class="welcome-text">
                    왼쪽에서 실제 CSV/Parquet 파일을 업로드하고 Claude 모델을 선택하세요.<br>
                    실행 중에는 현재 단계 한 줄만 표시되고 전체 로그는 결과의 상세보기에서 확인할 수 있습니다.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        suggestions = dataset_suggestions(current_dataset)
        if suggestions:
            st.markdown('<div class="quick-title">추천 질문</div>', unsafe_allow_html=True)
            columns = st.columns(len(suggestions))
            for column, suggestion in zip(columns, suggestions):
                with column:
                    if st.button(
                        suggestion,
                        use_container_width=True,
                        disabled=not chat_ready,
                        key=f"suggestion_{suggestion}",
                    ):
                        st.session_state.pending_prompt = suggestion
                        st.rerun()

    for idx, message in enumerate(st.session_state.messages):
        avatar = sunny_avatar if message.get("role") == "assistant" else "👤"
        with st.chat_message(message.get("role", "assistant"), avatar=avatar):
            if message.get("role") == "assistant":
                render_assistant_message(message, idx)
            else:
                st.markdown(str(message.get("content", "")))

if not dataset_ready:
    input_placeholder = "먼저 CSV 또는 Parquet 파일을 업로드해 주세요."
elif not model_ready:
    input_placeholder = "먼저 사이드바에서 Claude 모델을 선택해 주세요."
else:
    input_placeholder = "품질 데이터에 대해 질문해 주세요."

with st.bottom:
    typed_prompt = st.chat_input(
        input_placeholder,
        disabled=not chat_ready,
        key="main_chat_input",
    )

prompt = (st.session_state.pending_prompt or typed_prompt) if chat_ready else None

if prompt:
    st.session_state.pending_prompt = None
    user_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_message)

    with chat_area:
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=sunny_avatar):
            progress_line = st.empty()
            execution_steps: list[dict[str, Any]] = []

            icons = {
                "question_received": "💬",
                "dataset_resolving": "📁",
                "dataset_resolved": "✅",
                "engine_connecting": "🔌",
                "engine_connected": "✅",
                "schema_reading": "🧾",
                "schema_ready": "✅",
                "llm_connecting": "🤖",
                "llm_connected": "✅",
                "plan_generating": "🧠",
                "model_selected": "🤖",
                "tool_selected": "🧰",
                "sql_generated": "📝",
                "sql_validating": "🛡️",
                "sql_validated": "✅",
                "sql_rejected": "⚠️",
                "query_executing": "🔎",
                "query_completed": "✅",
                "python_executing": "🐍",
                "python_completed": "✅",
                "visualization_ready": "📊",
                "summary_generating": "✍️",
                "summary_fallback": "⚠️",
                "retrying": "🔄",
                "failed": "❌",
                "completed": "🎉",
            }

            def show_agent_progress(
                event: str,
                message: str,
                details: dict[str, Any],
            ) -> None:
                execution_steps.append(compact_step(event, message, details))
                icon = icons.get(event, "⏳")
                if event == "failed":
                    progress_line.error(f"{icon} {message}")
                elif event == "completed":
                    progress_line.success(f"{icon} {message}")
                else:
                    progress_line.info(f"{icon} {message}")

            try:
                result = run_data_agent(
                    question=prompt,
                    dataset_path=current_dataset,
                    on_progress=show_agent_progress,
                    model_candidates=model_candidates,
                )
                progress_line.empty()
                assistant_message = {
                    "role": "assistant",
                    "success": True,
                    "content": result.answer,
                    "data": result.dataframe.to_dict(orient="records"),
                    "verification": result.verification,
                    "steps": execution_steps,
                }
            except DataAgentError as exc:
                progress_line.empty()
                assistant_message = {
                    "role": "assistant",
                    "success": False,
                    "content": str(exc),
                    "error_detail": str(exc),
                    "steps": execution_steps,
                }

            render_assistant_message(assistant_message, len(st.session_state.messages))
            st.session_state.messages.append(assistant_message)
