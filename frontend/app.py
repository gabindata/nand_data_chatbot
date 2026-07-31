from __future__ import annotations

import base64
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image


# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
BACKGROUND_PATH = BASE_DIR / "assets" / "sunny_bg.png"
AVATAR_PATH = BASE_DIR / "assets" / "sunny_avatar.png"

st.set_page_config(
    page_title="SUNI 9조 데이터 챗봇",
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
# 결과 영역 자동 스크롤
# 입력창은 이제 CSS(flex 레이아웃)만으로 항상 화면 맨 아래에 고정되고,
# 결과 영역(.block-container)은 그 위에서 독립적으로 스크롤된다.
# 새 메시지가 추가될 때마다 결과 영역을 맨 아래로 자동 스크롤해서
# 사용자가 매번 손으로 내리지 않아도 최신 답변이 입력창 바로 위에 보이게 한다.
# 물론 사용자는 언제든 위로 스크롤해서 이전 결과를 자유롭게 볼 수 있다.
# ---------------------------------------------------------
components.html(
    """
    <script>
    (function () {
        const doc = window.parent.document;

        function findScrollArea() {
            return doc.querySelector('.block-container');
        }

        function scrollToBottom() {
            const el = findScrollArea();
            if (!el) return;
            el.scrollTop = el.scrollHeight;
        }

        function attach() {
            const el = findScrollArea();
            if (!el) {
                setTimeout(attach, 200);
                return;
            }

            // 최초 렌더링 및 스트림릿 재실행(rerun) 직후 맨 아래로 스크롤
            scrollToBottom();

            // 새 메시지/차트/표 등이 추가되어 콘텐츠 높이가 바뀔 때마다
            // 다시 맨 아래로 스크롤한다.
            const resizeObserver = new ResizeObserver(scrollToBottom);
            resizeObserver.observe(el);

            const mutationObserver = new MutationObserver(scrollToBottom);
            mutationObserver.observe(el, { childList: true, subtree: true });
        }

        attach();
    })();
    </script>
    """,
    height=0,
)


# ---------------------------------------------------------
# 상태 관리
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None


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
            <p class="brand-kicker">SUNI 9 TEAM</p>
            <p class="brand-title"SUNI 9조</p>
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
    st.markdown("##### 데이터 상태")
    st.markdown(
        """
        <div class="data-card">
            <div class="status-line">
                <span class="status-dot"></span>
                CSV 데이터 연결 완료
            </div>
            <div class="data-meta">
                전체 데이터: 약 20GB<br>
                조회 방식: 자연어 → SQL<br>
                현재 화면: UI 데모 모드
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.caption("SUNNY 9조 · UI Prototype v1.0")


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


_NUMBER_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)(건|%|원|개|명|위|년|월|일|배)?"
)


def highlight_numbers(text: str) -> str:
    """텍스트 내 숫자(및 붙은 단위)를 <span>으로 감싸 강조 표시한다."""

    def _wrap(match: re.Match) -> str:
        number, unit = match.group(1), match.group(2) or ""
        return f'<span class="stat-highlight">{number}{unit}</span>'

    return _NUMBER_PATTERN.sub(_wrap, text)


def render_assistant_message(message: dict[str, Any]) -> None:
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
        <h1 class="hero-title">SUNI 데이터 챗봇</h1>
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

        with st.status(
            "질문을 처리하고 있습니다.",
            expanded=True,
        ) as status:
            stages = [
                "사용자 질문을 분석하고 있습니다.",
                "질문과 관련된 테이블 및 컬럼을 확인하고 있습니다.",
                "자연어 질문을 SQL로 변환하고 있습니다.",
                "생성된 SQL의 정확도를 검증하고 있습니다.",
                "데이터를 조회하고 있습니다.",
                "조회 결과에 맞는 시각화를 준비하고 있습니다.",
            ]

            for stage in stages:
                status.write(f"⏳ {stage}")
                completed_steps.append(stage)
                time.sleep(0.38)

            answer, result_df, verification = create_demo_result(prompt)

            status.update(
                label="분석이 완료되었습니다.",
                state="complete",
                expanded=False,
            )

        assistant_message = {
            "role": "assistant",
            "content": answer,
            "data": result_df.to_dict(orient="records"),
            "verification": verification,
            "steps": completed_steps,
        }

        render_assistant_message(assistant_message)
        st.session_state.messages.append(assistant_message)
