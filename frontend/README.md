# frontend/

SUNNY 9조 품질 데이터 챗봇의 Streamlit UI입니다. 전체 아키텍처와 동작
원리는 [프로젝트 루트 README](../README.md)를 참고하세요. 이 문서는
`frontend/` 폴더 자체의 실행/구성 방법만 다룹니다.

## 실행 방법

### 가장 빠른 방법 (Windows)

1. 프로젝트 최상위 폴더에 `.env` 파일을 만들고 `ANTHROPIC_API_KEY`를
   넣습니다 (루트 README 참고).
2. `frontend/RUN_CHATBOT.bat`를 더블 클릭합니다. 필요한 패키지가
   자동으로 설치되고 브라우저가 열립니다.

### 터미널에서 직접 실행

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
```

`frontend/requirements.txt`는 `llm_sql/requirements.txt`를 상속하므로
DuckDB, Claude SDK 등 `llm_sql/` 의존성도 이 한 번의 설치로 함께
들어갑니다.

### 대용량 파일(10GB+)을 다뤄야 한다면

`frontend/`만으로는 부족하고, 별도 터미널에서 `backend/` FastAPI
서버도 함께 띄워야 합니다. 자세한 내용은 루트 README의 "대용량 파일을
다뤄야 할 때" 항목을 참고하세요.

```bash
uvicorn backend.upload_server:app --port 8000
```

## 화면 구성

- **사이드바**
  - 새 채팅 / 최근 대화 목록
  - CSV 업로드 (일반, ~수백 MB 이하)
  - 대용량 파일 업로드 (10GB+, backend 서버 직접 연결)
- **메인 화면**
  - 추천 질문 버튼 3개
  - 채팅 입력창 — 질문을 보내면 `llm_sql/app.py::answer_question()`이
    SQL 생성 → 검증 → 실행 → 요약까지 처리한 뒤, 답변 메시지 하단에
    다음 3개 탭으로 결과를 보여줍니다.
    - **핵심 결과**: 조회한 테이블, 인식한 컬럼, 조회 행 수
    - **데이터 표**: 실행 결과 전체 (표)
    - **시각화**: Claude가 함께 만들어 준 차트 힌트로 그린 막대/선/원
      그래프 (차트로 표현하기 애매한 결과는 빈 상태로 표시될 수 있음)
    - 그 아래 "SQL 및 검증 정보" 펼치기 — 생성된 SQL과 검증 통과 여부

데이터를 업로드하기 전에는 질문을 보낼 수 없고, 사이드바에 안내 문구가
표시됩니다.

## 실제 로직이 붙어있는 위치

이 폴더의 UI는 데모가 아니라 실제로 동작합니다. `frontend/app.py`는
`llm_sql/app.py`의 다음 함수들을 그대로 가져다 씁니다.

```python
from app import (
    get_duckdb_connection,
    load_into_duckdb,
    connect_latest_parquet,
    answer_question,
)
```

챗봇의 SQL 생성/검증/실행/요약 로직 자체를 수정하려면 이 폴더가 아니라
[`llm_sql/app.py`](../llm_sql/app.py)를 고치면 됩니다. `frontend/`는
그 결과를 화면에 그리는 역할만 합니다.

## 디자인 에셋

- `assets/sunny_bg.png`: 전체 배경
- `assets/sunny_avatar.png`: 챗봇 프로필 이미지
- `.streamlit/config.toml`: 테마 색상, 업로드 용량 상한
  (`maxUploadSize`, 현재 20GB) 설정
