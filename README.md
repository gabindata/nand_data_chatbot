# 💾 NAND Health Data Chatbot

대용량 NAND Health 데이터를 자연어로 분석할 수 있는 AI 기반 데이터 분석 챗봇입니다.

사용자가 복잡한 SQL이나 Python 코드를 직접 작성하지 않아도 자연어로 질문하면, LLM이 질문을 SQL로 변환하고 DuckDB가 실제 데이터를 정확하게 분석합니다.

> **LLM은 질문을 이해하고 SQL로 변환하며, 실제 데이터 집계와 계산은 DuckDB가 수행합니다.**

---

## 📌 프로젝트 배경

NAND 메모리의 Health 데이터에는 다음과 같은 정보가 포함될 수 있습니다.

* NAND 유닛 식별자
* PE Cycle
* 불안정 횟수
* 모델
* 용량
* 온도
* 오류 횟수
* 사용 시간

기존에는 새로운 분석 조건이 필요할 때마다 Python 코드를 직접 작성해야 했습니다.

예를 들어:

> PE Cycle이 300 이상인 NAND는 몇 개인가?

라는 질문에 답하기 위해 직접 코드를 작성해야 했습니다.

본 프로젝트는 이러한 문제를 해결하기 위해 **자연어 질문 → SQL 변환 → 대용량 데이터 분석 → 자연어 결과 요약**의 과정을 자동화합니다.

---

## 🎯 프로젝트 목표

### 1. 대용량 데이터의 정확한 분석

10~20GB 수준의 대용량 NAND Health 데이터를 LLM에 직접 전달하지 않고, 데이터베이스 엔진이 직접 계산하도록 설계합니다.

LLM이 데이터를 직접 계산하지 않기 때문에 대규모 데이터의 집계 결과를 정확하게 처리할 수 있습니다.

### 2. 비전문가의 데이터 접근성 향상

SQL이나 Python을 모르는 사용자도 자연어로 질문하여 데이터를 분석할 수 있도록 합니다.

```text
"온도가 80도 이상이고 오류가 10개 이상인 NAND를 찾아줘"
```

와 같은 질문을 입력하면 시스템이 자동으로 분석을 수행합니다.

---

## 🏗️ 시스템 구조

```text
┌─────────────────────┐
│   사용자 Excel 업로드 │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   청크 단위 업로드    │
│      FastAPI         │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Excel → Parquet     │
│      변환             │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    DuckDB 연결       │
│   read_parquet()     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    자연어 질문       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  LLM: 자연어 → SQL   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ DuckDB SQL 실행      │
│ 실제 데이터 집계     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   분석 결과 출력     │
│   + AI 자연어 요약   │
└─────────────────────┘
```

---

## ✨ 주요 기능

### 📁 1. 대용량 파일 청크 업로드

대용량 파일을 한 번에 업로드하지 않고 여러 개의 청크로 분할하여 업로드합니다.

```text
대용량 Excel
    ↓
100MB 단위 청크 분할
    ↓
청크별 업로드
    ↓
서버에서 파일 재조립
```

이를 통해 대용량 파일 업로드 중 메모리 부담을 줄이고 업로드 진행 상황을 표시할 수 있습니다.

---

### 🔄 2. Excel → Parquet 자동 변환

업로드가 완료되면 Excel 파일을 분석에 적합한 Parquet 형식으로 변환합니다.

```text
.xlsx
  ↓
Parquet 변환
  ↓
nand_health.parquet
```

Parquet는 분석에 적합한 컬럼 기반 저장 형식이므로 이후 DuckDB에서 직접 조회할 수 있습니다.

---

### ⚡ 3. DuckDB 기반 데이터 분석

DuckDB를 사용하여 Parquet 데이터를 SQL로 분석합니다.

```sql
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;
```

DuckDB가 실제 데이터 집계와 계산을 담당하기 때문에 LLM이 숫자를 직접 계산하지 않습니다.

---

### 🤖 4. 자연어 → SQL 자동 변환

사용자가 자연어로 질문하면 LLM이 DuckDB에서 실행할 SQL을 생성합니다.

사용자 질문:

```text
PE Cycle이 900 이상이고 unstable_count가 5 이상인 NAND의 평균 온도를 알려줘.
```

생성되는 SQL:

```sql
SELECT AVG(temperature_c)
FROM nand_health
WHERE pe_cycle >= 900
  AND unstable_count >= 5;
```

---

### 🧠 5. 분석 결과 자연어 요약

SQL 실행 결과를 LLM이 다시 자연어로 요약합니다.

```text
PE Cycle이 900 이상이고 unstable_count가 5 이상인
NAND의 평균 온도는 65.2도입니다.
```

이를 통해 사용자가 SQL 결과를 직접 해석하지 않아도 됩니다.

---

### 🚨 6. NAND 위험도 분석

`CASE WHEN`을 활용하여 NAND Health 데이터를 위험 점수로 분류할 수 있습니다.

예시:

```sql
SELECT
    CASE
        WHEN error_count > 10 THEN 3
        WHEN unstable_count > 5 THEN 2
        WHEN pe_cycle > 1000 THEN 1
        ELSE 0
    END AS risk_score,
    COUNT(*) AS unit_count
FROM nand_health
GROUP BY risk_score;
```

이를 통해 전체 NAND를 위험도별로 분류할 수 있습니다.

---

## 📊 현재 검증된 SQL 분석 기능

현재 시스템에서 다음 SQL 기능을 실제 데이터로 검증했습니다.

| 기능          | 상태 |
| ----------- | -- |
| `COUNT`     | ✅  |
| `AVG`       | ✅  |
| `SUM`       | ✅  |
| `WHERE`     | ✅  |
| `AND / OR`  | ✅  |
| `GROUP BY`  | ✅  |
| `ORDER BY`  | ✅  |
| `LIMIT`     | ✅  |
| `CASE WHEN` | ✅  |
| 모델별 집계      | ✅  |
| 복수 조건 분석    | ✅  |
| 위험도 분류      | ✅  |

---

## 🧪 성능 검증

현재 테스트 데이터 기준으로:

```text
파일 크기: 약 300MB
데이터 수: 3,000,000개
```

의 NAND Health 데이터를 대상으로 다음 분석을 성공적으로 수행했습니다.

### 예시 1 — 조건부 개수 조회

```sql
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;
```

### 예시 2 — 모델별 평균 분석

```sql
SELECT
    model,
    AVG(temperature_c) AS average_temperature,
    AVG(pe_cycle) AS average_pe_cycle
FROM nand_health
GROUP BY model;
```

### 예시 3 — 오류 상위 NAND 조회

```sql
SELECT *
FROM nand_health
ORDER BY error_count DESC
LIMIT 10;
```

### 예시 4 — 복합 조건 분석

```sql
SELECT *
FROM nand_health
WHERE temperature_c >= 80
  AND error_count >= 15;
```

### 예시 5 — 위험도 점수 계산

```sql
SELECT
    unit_id,
    CASE
        WHEN temperature_c > 70
         AND pe_cycle > 900
         AND error_count > 10
        THEN 3
        ELSE 0
    END AS risk_score
FROM nand_health
ORDER BY risk_score DESC
LIMIT 10;
```

---

## 🛠️ 기술 스택

### Frontend / UI

* **Streamlit**

  * 챗봇 UI
  * 파일 업로드
  * 분석 결과 표시

### Backend

* **FastAPI**

  * 대용량 파일 업로드 API
  * 청크 업로드 처리
  * 업로드 파일 관리

### Data Processing

* **Polars**

  * 데이터 처리
  * Excel → Parquet 변환

* **Parquet**

  * 컬럼 기반 분석용 데이터 저장 형식

* **DuckDB**

  * SQL 기반 대용량 데이터 분석 엔진
  * Parquet 직접 조회

### AI

* **OpenAI API**

  * 자연어 → SQL 변환
  * 분석 결과 자연어 요약

### Collaboration

* **GitHub**

  * 소스 코드 관리
  * 버전 관리
  * 팀 협업

---

## 📂 프로젝트 구조

```text
nand_data_chatbot/
│
├── app.py
│   └── Streamlit 기반 메인 챗봇 애플리케이션
│
├── upload_server.py
│   └── FastAPI 기반 대용량 파일 업로드 서버
│
├── large_upload.html
│   └── 청크 단위 대용량 파일 업로드 UI
│
├── convert_excel.py
│   └── Excel 변환 관련 코드
│
├── convert_to_parquet.py
│   └── Excel → Parquet 변환 로직
│
├── create_parquet.py
│   └── Parquet 데이터 생성 및 테스트 코드
│
├── make_excel.py
│   └── 테스트용 Excel 데이터 생성 코드
│
├── test_parquet.py
│   └── Parquet 데이터 테스트 코드
│
├── .streamlit/
│   └── Streamlit 설정 파일
│
├── .gitignore
│   └── 대용량 데이터 및 민감 정보 제외 설정
│
└── README.md
    └── 프로젝트 설명서
```

---

## 🚀 실행 방법

### 1. 저장소 클론

```bash
git clone https://github.com/gabindata/nand_data_chatbot.git
cd nand_data_chatbot
```

---

### 2. 필요한 라이브러리 설치

```bash
pip install -r requirements.txt
```

또는 필요한 패키지를 직접 설치합니다.

```bash
pip install streamlit
pip install polars
pip install duckdb
pip install fastapi
pip install uvicorn
pip install openai
pip install requests
```

---

### 3. OpenAI API 키 설정

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-api-key"
```

또는 `.env` 파일을 사용하는 경우:

```text
OPENAI_API_KEY=your-api-key
```

> ⚠️ API 키는 절대 GitHub에 업로드하지 않습니다.

---

### 4. FastAPI 업로드 서버 실행

```bash
uvicorn upload_server:app --reload
```

서버 주소:

```text
http://127.0.0.1:8000
```

---

### 5. Streamlit 앱 실행

새 터미널에서:

```bash
streamlit run app.py
```

이후 브라우저에서 Streamlit이 제공하는 주소로 접속합니다.

---

## 🔐 데이터 보안

본 시스템은 실제 원본 데이터를 LLM에 직접 전달하지 않는 구조를 목표로 합니다.

LLM에 전달되는 정보:

```text
컬럼 설명
+
사용자 질문
```

LLM에 직접 전달되지 않는 정보:

```text
원본 NAND Health 데이터 전체
```

실제 데이터 분석은 DuckDB가 수행하고, LLM은 SQL 생성과 결과 요약을 담당합니다.

> 실제 업무 데이터 적용 시 외부 LLM API 사용에 대한 사내 보안 정책 검토가 필요합니다.

---

## 🚧 현재 한계

### 1. 초대형 Excel 처리

현재 300MB, 300만 행 데이터에 대한 동작을 검증했습니다.

10~20GB 규모의 Excel 파일은 Excel 파일 구조와 시스템 메모리에 따라 추가적인 최적화가 필요합니다.

향후에는 다음과 같은 구조를 고려합니다.

```text
대용량 Excel
    ↓
분할 처리
    ↓
여러 개의 Parquet 파일
    ↓
DuckDB에서 Parquet 전체 조회
```

예:

```text
converted_parquet/
├── part_0001.parquet
├── part_0002.parquet
├── part_0003.parquet
└── ...
```

---

### 2. 자연어 질문의 SQL 정확도

LLM이 생성하는 SQL이 항상 정확한 것은 아니므로 다음 기능이 필요합니다.

* SQL 생성 결과 검증
* 허용된 컬럼만 사용하도록 제한
* 위험한 SQL 명령 차단
* 테스트 질문셋 기반 정확도 검증

현재 시스템은 `SELECT` 중심의 SQL만 허용하고 위험한 SQL 명령어를 차단합니다.

---

### 3. 시각화 자동 선택

향후 결과 형태에 따라 자동으로 적합한 시각화를 선택하는 기능을 추가할 예정입니다.

```text
단일 값
    → Metric

범주별 집계
    → Bar Chart

시간별 변화
    → Line Chart

상세 목록
    → Data Table
```

---

## 🗺️ 개발 로드맵

### ✅ Phase 1 — 최소 동작 검증

* [x] Excel 데이터 분석
* [x] 자연어 질문 입력
* [x] LLM 기반 SQL 생성
* [x] DuckDB SQL 실행
* [x] 결과 출력
* [x] AI 결과 요약

### 🟡 Phase 2 — 사용 가능한 챗봇 완성

* [x] 대용량 파일 청크 업로드
* [x] Excel → Parquet 자동 변환
* [x] Parquet → DuckDB 연결
* [x] 대용량 데이터 분석
* [ ] 결과 형태별 자동 시각화
* [ ] 후속 질문 추천
* [ ] 분석 결과 다운로드
* [ ] 더욱 다양한 오류 처리

### 🔜 Phase 3 — 차수 간 비교 분석

* [ ] 1차수 / 2차수 데이터 업로드
* [ ] 카테고리별 수치 비교
* [ ] 증감량 계산
* [ ] 증가 / 감소 추세 분석
* [ ] 트렌드 시각화

### 🔮 Future

* [ ] 10~20GB 이상 데이터 처리 최적화
* [ ] 테스트 질문셋 기반 Text-to-SQL 정확도 평가
* [ ] 사내 LLM 또는 오픈소스 LLM 지원
* [ ] 사용자별 분석 기록
* [ ] 분석 결과 다운로드
* [ ] 대시보드 기능 확장

---

## 🎯 핵심 설계 원칙

### 1. LLM에게 계산을 맡기지 않는다

```text
❌ LLM이 300만 개 데이터를 직접 계산

✅ LLM이 SQL을 생성
      ↓
   DuckDB가 계산
```

---

### 2. 원본 데이터와 분석 형식을 분리한다

```text
원본 데이터
Excel
  ↓
분석용 변환
Parquet
  ↓
SQL 분석
DuckDB
```

---

### 3. 사용자는 SQL을 몰라도 된다

```text
사용자:
"오류가 가장 많은 NAND 10개를 보여줘"

시스템:
→ SQL 자동 생성
→ DuckDB 실행
→ 결과 출력
→ 자연어 요약
```

---

## 👥 팀 역할

| 역할                      | 주요 업무                                   |
| ----------------------- | --------------------------------------- |
| PM / Prompt Engineer    | 프로젝트 관리, 프롬프트 설계, 테스트 질문셋 관리            |
| Frontend Developer      | Streamlit UI, 파일 업로드, 결과 화면             |
| Backend / Data Engineer | FastAPI, Excel → Parquet → DuckDB 파이프라인 |
| AI Agent Engineer       | Text-to-SQL 로직, SQL 검증, AI 에이전트         |
| ML / Model Engineer     | 로컬 LLM 서빙, 모델 최적화, 파인튜닝                 |

---

## 📌 프로젝트 핵심 가치

이 프로젝트의 핵심은 단순히 **AI에게 데이터를 맡기는 것**이 아닙니다.

> **AI는 자연어를 이해하고, 데이터베이스는 정확하게 계산한다.**

각 기술이 가장 잘하는 역할을 분리함으로써:

* 대용량 데이터 처리
* 계산 정확성
* 자연어 접근성
* 분석 자동화

를 동시에 달성하는 것을 목표로 합니다.

---

## 📄 License

This project is for educational and project development purposes.
