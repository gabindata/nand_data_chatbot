# NAND Health 품질 데이터 챗봇 (SUNNY 9조)

CSV로 업로드한 NAND/UFS 품질 데이터를 자연어로 질문하면, Claude가 SQL을
생성해 DuckDB로 조회하고 표·그래프·요약으로 보여주는 사내용 챗봇입니다.

## 아키텍처

```
브라우저 (Streamlit UI)
   │
   ├─ 일반 업로드: st.file_uploader → 메모리로 읽어 DuckDB에 바로 로드
   │                (frontend/app.py → llm_sql/app.py::load_into_duckdb)
   │
   └─ 대용량 업로드(10GB+): 브라우저가 Streamlit을 거치지 않고
      backend(FastAPI)로 직접 청크 업로드
                      │
                      ▼
      backend/upload_server.py  (청크 합치기 → CSV → parquet 변환)
                      │
                      ▼
      llm_sql/app.py::connect_latest_parquet()
      → DuckDB가 parquet 파일을 뷰(uploaded_data)로 직접 연결

질문 처리:
  자연어 질문
     → Claude: SQL + 차트 힌트(JSON) 생성 (llm_sql/app.py::generate_sql_and_chart)
     → SQL 검증 (SELECT만 허용, 컬럼/함수 화이트리스트)   (validate_sql)
     → 결과 행수 상한(5,000행) 적용                        (_apply_row_limit)
     → DuckDB 실행
     → 차트 힌트를 실제 결과 컬럼과 대조해 최종 확정
     → Claude: 결과 요약(미리보기 기반)                     (summarize_result)
     → Streamlit에 답변 + 표 + 그래프 + SQL/검증 정보 표시
```

DuckDB는 세션(브라우저 탭)마다 새로 뜨는 인메모리 커넥션입니다. 데이터는
파일(parquet)이나 그때그때 업로드한 CSV를 가리키는 **뷰**로만 연결되며,
DB 자체에 영구 저장되지는 않습니다.

## 폴더 구조

| 폴더 | 역할 |
| --- | --- |
| [`frontend/`](frontend) | Streamlit UI. 실제로 실행하는 앱 (`streamlit run frontend/app.py`) |
| [`llm_sql/`](llm_sql) | 핵심 로직 모듈. DuckDB 연결, Claude 호출(SQL/차트 생성, 결과 요약), SQL 검증. `frontend/app.py`가 import해서 사용 |
| [`backend/`](backend) | 대용량 파일 업로드용 FastAPI 서버. 브라우저가 Streamlit을 거치지 않고 직접 청크 업로드하는 대상 |
| [`data_pipeline/`](data_pipeline) | 실제 원본 파일(엑셀/CSV)을 parquet으로 변환하는 CLI 스크립트 |
| [`dummy_data/`](dummy_data) | 성능/용량 테스트용 가짜 데이터 생성 스크립트 (실 서비스와 무관) |
| `data/` | 샘플 테스트 데이터 (`nand_health_test.csv` / `.parquet`) |

각 폴더의 세부 사용법은 폴더 안의 README(`frontend/README.md`,
`data_pipeline/README.md`, `dummy_data/README.md`)를 참고하세요.

## 시작하기

### 1. 환경 변수

프로젝트 최상위 폴더에 `.env` 파일을 만들고 Claude API 키를 넣습니다.

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

`llm_sql/app.py`가 시작 시 이 값을 읽으며, 없으면 바로 에러를 냅니다.

### 2. 설치 및 실행 (일반 파일, ~수백 MB 이하)

```bash
pip install -r frontend/requirements.txt
streamlit run frontend/app.py
```

`frontend/requirements.txt`는 `llm_sql/requirements.txt`를 상속하므로
이 한 번의 설치로 `llm_sql/` 의존성(DuckDB, Claude SDK 등)까지 함께
설치됩니다. Windows에서는 `frontend/RUN_CHATBOT.bat`를 더블 클릭해도
됩니다.

브라우저에서 사이드바의 "CSV 파일을 선택하세요"로 파일을 올리면 바로
질문할 수 있습니다.

### 3. 대용량 파일(10GB+)을 다뤄야 할 때

일반 업로드는 파일을 폴라스(polars)로 전량 메모리에 읽어들이기 때문에
수십 GB 파일에는 적합하지 않습니다. 이 경우 별도 창(터미널)에서 backend
서버를 함께 띄우세요.

```bash
pip install -r backend/requirements.txt
uvicorn backend.upload_server:app --port 8000
```

그 다음 Streamlit 사이드바의 "대용량 파일 업로드 (10GB+)"를 펼쳐서
CSV를 선택하고 "업로드 시작"을 누르면, 브라우저가 Streamlit을 거치지
않고 이 FastAPI 서버로 직접 청크 단위(기본 100MB)로 전송합니다. 서버가
CSV를 스트리밍 방식으로 parquet으로 변환한 뒤, "업로드한 데이터
불러오기" 버튼을 누르면 DuckDB가 그 parquet 파일을 뷰로 연결합니다.

backend 서버 주소가 `127.0.0.1:8000`이 아니라면 환경 변수
`UPLOAD_SERVER_URL`로 바꿀 수 있습니다.

```bash
UPLOAD_SERVER_URL=http://내부서버주소:8000 streamlit run frontend/app.py
```

## 동작 원리 (자연어 → SQL 파이프라인)

1. **스키마 동적 조회** — 업로드된 파일의 실제 컬럼/타입을 `DESCRIBE
   uploaded_data`로 매번 읽습니다. 컬럼이 파일마다 달라도 코드 수정이
   필요 없습니다.
2. **SQL + 차트 힌트 생성** — Claude에게 스키마와 질문을 주고, SQL과
   차트 정보(`{"type", "x", "y"}` 또는 `null`)를 JSON 하나로 함께
   요청합니다.
3. **SQL 검증** (`validate_sql`) — 다음을 만족하지 않으면 실행하지
   않습니다.
   - `SELECT` 문 하나만 허용 (`DROP`/`DELETE`/`INSERT`/`CREATE` 등 차단)
   - 테이블은 `uploaded_data`만 허용
   - 컬럼은 현재 파일에 실제로 존재하는 것만 허용
   - 함수는 정해진 화이트리스트만 허용 (`COUNT`, `AVG`, `SUBSTR`,
     `STDDEV` 등 — 전체 목록은 `llm_sql/app.py`의 `SQL_FUNCTIONS`)
4. **결과 행수 상한** — 쿼리에 `LIMIT`이 없으면 자동으로
   `LIMIT 5000`을 붙입니다. 수십 GB 데이터에서 조건 없는 질문이 전체
   결과를 그대로 끌고 오는 것을 막기 위함입니다.
5. **차트 힌트 재검증** — 1번에서 받은 차트의 x/y 컬럼명이 실제 실행
   결과 컬럼에 없으면 차트를 표시하지 않습니다(빈 힌트로 무시).
6. **결과 요약** — 결과가 30행을 넘으면 앞 30행만 프롬프트에 넣어
   요약을 요청합니다(전체 행수는 별도로 언급). 토큰 비용을 통제하기
   위함입니다.

## 알려진 제약

- SELECT 조회만 가능하며, 조회 결과는 한 번에 최대 5,000행까지만
  화면에 표시됩니다.
- 대용량 업로드 경로는 "가장 최근 업로드한 데이터셋 하나"만 유지하는
  구조입니다(다중 사용자가 각자 다른 데이터셋을 동시에 쓰는 용도가
  아닙니다).
- `backend/upload_server.py`는 CSV만 자동 변환합니다. 엑셀 원본은
  `data_pipeline/convert_excel.py`로 먼저 parquet으로 만들어야 합니다.
