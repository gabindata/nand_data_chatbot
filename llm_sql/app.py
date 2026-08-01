"""
NAND Health 챗봇의 AI+SQL 로직 모듈.

주의: 이 파일은 더 이상 자체 Streamlit 페이지가 아니다 (st.set_page_config,
st.title, 데이터 입력 모드 선택 UI, 채팅 렌더링을 모두 제거했다).
화면(UI)은 frontend/app.py가 담당하고, 이 모듈은 아래 함수들만 제공한다.

frontend/README.md 에 정의된 통합 방식대로,
frontend/app.py 의 create_demo_result(question) 자리에
이 모듈의 answer_question(con, question)을 호출하도록 바꾸면
실제 데이터로 연결된다.

제공 함수:
- get_duckdb_connection(): DuckDB 커넥션 생성
- load_csv_into_duckdb(con, csv_file): 업로드된 CSV를 nand_health 뷰로 등록
- connect_latest_parquet(con, upload_server_url): backend 서버에 최근 업로드된
  parquet을 nand_health 뷰로 연결
- upload_file_in_chunks(file_path, upload_server_url): 대용량 파일을
  backend/upload_server.py 로 청크 업로드 (진행률 표시 포함)
- answer_question(con, question): 자연어 질문 1개를 SQL 생성 -> 검증 -> 실행 ->
  요약까지 수행하고 결과 dict를 반환
"""

import polars as pl
import duckdb
import os
import requests
import re
from dotenv import load_dotenv
from anthropic import Anthropic
import streamlit as st  # upload_file_in_chunks의 진행률 표시(st.progress 등) 용도로만 사용

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 프로젝트 최상위 폴더(nand_data_chatbot/.env)에 적어둔 환경변수(ANTHROPIC_API_KEY)를
# 실행 위치(cwd)와 상관없이 항상 불러오도록 경로를 명시한다.
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

LARGE_UPLOAD_HTML_PATH = os.path.join(
    BASE_DIR, "..", "backend", "large_upload.html"
)

# =====================================
# SQL 검증 설정
# =====================================

ALLOWED_TABLE = "nand_health"

ALLOWED_COLUMNS = {
    "vednor",
    "density",
    "pn",
    "storage_used_already",
    "storage_utilization",
    "ufsid",
    "rtbb",
    "uecc",
    "tbw",
    "pe_cycle",
    "tbr",
    "reserved_b",
    "spocount",
    "read_reclaim",
    "init_count",
    "vcc_count",
    "vccq_count",
    "ffu_count",
    "bedccount",
    "bchecksumcount",
    "bundefinstcount"
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


# =====================================
# Claude(Anthropic) API 설정
# =====================================

api_key = os.environ.get("ANTHROPIC_API_KEY")

if not api_key:
    raise RuntimeError(
        "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
        "프로젝트 최상위 폴더의 .env 파일에 키를 넣어주세요."
    )

client = Anthropic(api_key=api_key)

# SQL 생성/요약에 사용할 모델 (구매한 플랜 기준 Claude Sonnet 5)
# 참고: Anthropic API는 model을 반드시 명시해야 하며 기본값이 없다.
CLAUDE_MODEL = "claude-sonnet-5"


# =====================================
# 데이터 연결 기능
# =====================================

def get_duckdb_connection():
    """이 모듈 전용 DuckDB 커넥션을 새로 만든다."""
    return duckdb.connect()


def load_csv_into_duckdb(con, csv_file) -> int:
    """
    업로드된 CSV(파일 객체 또는 경로)를 nand_health 뷰로 등록한다.
    반환값은 로드된 행(row) 수.
    """
    data = pl.read_csv(csv_file)

    con.register("uploaded_data", data)

    con.execute("""
        CREATE OR REPLACE VIEW nand_health AS
        SELECT *
        FROM uploaded_data
    """)

    return data.height


def connect_latest_parquet(con, upload_server_url: str = "http://127.0.0.1:8000") -> str:
    """
    backend/upload_server.py 에 최근 업로드된 parquet 파일을
    nand_health 뷰로 연결한다. 연결한 parquet 파일 경로를 반환한다.
    """
    response = requests.get(
        f"{upload_server_url}/upload/latest",
        timeout=3
    )

    response.raise_for_status()

    upload_info = response.json()

    final_file_path = upload_info["file_path"]

    con.execute(
        f"""
        CREATE OR REPLACE VIEW nand_health AS
        SELECT *
        FROM read_parquet(
            '{final_file_path}'
        )
        """
    )

    return final_file_path


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


# =====================================
# 컬럼 스키마 설명 (Claude 프롬프트용)
# =====================================

schema = """
테이블명: nand_health

컬럼 정의:

- vednor
  의미: Memory 회사(제조사) 이름
  사용자 표현: 회사, 제조사, 벤더, 브랜드

- density
  의미: UFS Memory 총 용량
  사용자 표현: 용량, 총 용량, 메모리 용량, 저장 용량 스펙

- pn
  의미: UFS 제품 Part No.
  사용자 표현: 제품 번호, Part No, 품번, 모델명

- storage_used_already
  의미: UFS Memory 실제 사용 중인 용량
  사용자 표현: 사용 용량, 사용한 용량, 사용 중인 용량, 사용량

- storage_utilization
  의미: UFS Memory 총 용량 대비 사용 용량 비율(Portion)
  사용자 표현: 사용률, 사용 비율, 용량 대비 사용률, 얼마나 찼는지

- ufsid
  의미: UFS 고유 ID
  사용자 표현: 고유 ID, UFS ID, 장치 ID, 시리얼, 식별자

- rtbb
  의미: Run Time Bad Block, UFS에서 불량이 발생한 Block 개수
  사용자 표현: 불량 블록, 런타임 불량 블록, Bad Block, 불량 블록 개수

- uecc
  의미: Uncorrected Error Correction Code, 정정되지 않은 Bit Error 발생 횟수
  사용자 표현: 비트 에러, 비트 오류, 정정 안 된 에러, UECC, 오류, 에러

- tbw
  의미: Total Byte Written, UFS의 누적 쓰기량(Lifetime)
  사용자 표현: 총 쓰기량, TBW, 누적 쓰기 바이트, 라이프타임 쓰기량

- pe_cycle
  의미: UFS Block을 쓰고 지운 횟수
  사용자 표현: PE Cycle, PE 사이클, PE, 쓰고 지운 횟수

- tbr
  의미: Total Byte Read, UFS의 누적 읽기량
  사용자 표현: 총 읽기량, TBR, 누적 읽기 바이트, 읽은 용량

- reserved_b
  의미: UFS의 Reserved Block 개수
  사용자 표현: 예비 블록, Reserved Block, 리저브 블록

- spocount
  의미: Sudden Power Off Count, 갑자기 Memory Power가 끊긴 횟수
  사용자 표현: 전원 급차단, SPO, Sudden Power Off, 갑작스러운 전원 차단 횟수

- read_reclaim
  의미: Read Refresh(Read Reclaim)를 수행한 횟수
  사용자 표현: 리드 리클레임, Read Reclaim, 리드 리프레시 횟수

- init_count
  의미: 초기화 횟수 (상세 정의 없음)
  사용자 표현: 초기화 횟수, Init Count

- vcc_count
  의미: VCC Power가 Spec 이하로 떨어진 횟수
  사용자 표현: VCC 전압 이상 횟수, VCC Power 저하 횟수, VCC 카운트

- vccq_count
  의미: VCCQ Power가 Spec 이하로 떨어진 횟수
  사용자 표현: VCCQ 전압 이상 횟수, VCCQ Power 저하 횟수, VCCQ 카운트

- ffu_count
  의미: Firmware Update 횟수
  사용자 표현: 펌웨어 업데이트 횟수, FFU, Firmware Update 횟수

- bedccount
  의미: bEDCCount (상세 정의 없음)
  사용자 표현: bEDCCount, EDC 카운트

- bchecksumcount
  의미: bChecksumCount (상세 정의 없음)
  사용자 표현: bChecksumCount, 체크섬 카운트

- bundefinstcount
  의미: bUndefINSTCount (상세 정의 없음)
  사용자 표현: bUndefINSTCount, 정의되지 않은 명령 카운트
"""


def _build_sql_prompt(question: str) -> str:
    return f"""
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

vednor
density
pn
storage_used_already
storage_utilization
ufsid
rtbb
uecc
tbw
pe_cycle
tbr
reserved_b
spocount
read_reclaim
init_count
vcc_count
vccq_count
ffu_count
bedccount
bchecksumcount
bundefinstcount

==================================================
3. 컬럼 의미 매핑 규칙
==================================================

사용자의 표현이 아래 목록에 포함되면
반드시 해당 컬럼을 사용한다.

[회사/제품 식별 관련]
"회사"
"제조사"
"벤더"
"브랜드"
→ vednor

"제품 번호"
"Part No"
"품번"
"모델명"
→ pn

"고유 ID"
"UFS ID"
"장치 ID"
"시리얼"
"식별자"
→ ufsid

[용량 관련]
"총 용량"
"메모리 용량"
"저장 용량 스펙"
→ density

"사용 용량"
"사용한 용량"
"사용 중인 용량"
"사용량"
→ storage_used_already

"사용률"
"사용 비율"
"용량 대비 사용률"
→ storage_utilization

[불량/오류 관련]
"불량 블록"
"런타임 불량 블록"
"Bad Block"
→ rtbb

"비트 에러"
"비트 오류"
"정정 안 된 에러"
"UECC"
"오류"
"에러"
→ uecc

[쓰기/읽기 관련]
"총 쓰기량"
"TBW"
"누적 쓰기 바이트"
→ tbw

"총 읽기량"
"TBR"
"누적 읽기 바이트"
"읽은 용량"
→ tbr

"PE"
"PE Cycle"
"PE 사이클"
"쓰고 지운 횟수"
→ pe_cycle

[전원/전압 관련]
"전원 급차단"
"SPO"
"Sudden Power Off"
→ spocount

"VCC 전압 이상"
"VCC Power 저하"
→ vcc_count

"VCCQ 전압 이상"
"VCCQ Power 저하"
→ vccq_count

[기타 카운트 관련]
"예비 블록"
"Reserved Block"
→ reserved_b

"리드 리클레임"
"Read Reclaim"
"리드 리프레시"
→ read_reclaim

"초기화 횟수"
"Init Count"
→ init_count

"펌웨어 업데이트"
"FFU"
"Firmware Update"
→ ffu_count

"bEDCCount"
"EDC 카운트"
→ bedccount

"bChecksumCount"
"체크섬 카운트"
→ bchecksumcount

"bUndefINSTCount"
"정의되지 않은 명령 카운트"
→ bundefinstcount

==================================================
4. 절대 혼동하면 안 되는 컬럼
==================================================

불량 블록과 비트 에러는 서로 다른 개념이다.

"불량 블록", "Bad Block"
→ rtbb

"비트 에러", "UECC"
→ uecc

절대 다음과 같이 해석하지 않는다.

불량 블록 → uecc ❌
비트 에러 → rtbb ❌

쓰기량과 읽기량도 서로 다른 개념이다.

쓰기량 → tbw
읽기량 → tbr

총 용량, 사용 용량, 사용률도 서로 다른 개념이다.

총 용량 → density
사용 용량 → storage_used_already
사용률 → storage_utilization

VCC와 VCCQ도 서로 다른 전원 레일이다.

VCC 관련 → vcc_count
VCCQ 관련 → vccq_count

==================================================
5. 질문에 명시된 조건만 사용
==================================================

사용자가 질문에서 언급하지 않은 조건을
임의로 추가하지 않는다.

예를 들어:

사용자:
"불량 블록이 70개보다 많은 UFS는 몇 개야?"

올바른 SQL:
SELECT COUNT(*)
FROM nand_health
WHERE rtbb > 70;

잘못된 SQL:
SELECT COUNT(*)
FROM nand_health
WHERE rtbb > 70
AND uecc > 10;

비트 에러 조건은 사용자가 말하지 않았으므로 추가하면 안 된다.

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

1. rtbb를 임의로 선택하지 않는다.
2. uecc를 임의로 선택하지 않는다.
3. pe_cycle을 임의로 선택하지 않는다.
4. tbw, tbr을 임의로 선택하지 않는다.
5. spocount를 임의로 선택하지 않는다.
6. vcc_count, vccq_count를 임의로 선택하지 않는다.
7. storage_utilization을 임의로 선택하지 않는다.
8. 여러 컬럼을 임의로 조합하지 않는다.
9. rtbb > 0 조건을 임의로 추가하지 않는다.
10. uecc > 0 조건을 임의로 추가하지 않는다.
11. pe_cycle > 특정 값 조건을 임의로 추가하지 않는다.
12. storage_utilization > 특정 값 조건을 임의로 추가하지 않는다.

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
"비트 에러가 10개 이상이고 불량 블록이 5개 이상인
고장 위험 UFS는 몇 개야?"

→ 명시된 조건만 사용:

uecc >= 10
AND rtbb >= 5

예상 SQL:

SELECT COUNT(*)
FROM nand_health
WHERE uecc >= 10
AND rtbb >= 5;

예시 3:

사용자 질문:
"사용률이 90% 이상인 UFS를 고장 위험으로 보고
몇 개야?"

→ 사용자가 사용률 기준을 직접 제시했으므로:

SELECT COUNT(*)
FROM nand_health
WHERE storage_utilization >= 0.9;

예시 4:

사용자 질문:
"PE Cycle이 1000 이상인 오래된 UFS는 몇 개야?"

→ PE Cycle 기준만 사용:

SELECT COUNT(*)
FROM nand_health
WHERE pe_cycle >= 1000;

예시 5:

사용자 질문:
"전원 급차단이 10회 이상인 UFS는 몇 개야?"

→ 전원 급차단 기준만 사용:

SELECT COUNT(*)
FROM nand_health
WHERE spocount >= 10;

==================================================
모호한 표현과 구체적 조건의 우선순위
==================================================

"고장", "위험", "불량", "상태가 안 좋다",
"건강하지 않다"와 같은 표현은
그 자체로 SQL 조건이 아니다.

반드시 질문에 명시된 구체적인 수치 조건만 사용한다.

예:

"고장날 것 같은 UFS 중에서 불량 블록이 70개 이상인 것은 몇 개야?"

→ "고장날 것 같다"는 모호한 표현이므로 무시한다.
→ 명시된 불량 블록 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE rtbb >= 70;

예:

"문제가 있는 UFS 중 비트 에러가 10개 이상인 것은 몇 개야?"

→ "문제가 있는 UFS"는 모호한 표현이므로 무시한다.
→ 명시된 비트 에러 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE uecc >= 10;

예:

"건강한 UFS 중 사용률이 50% 이하인 것은 몇 개야?"

→ "건강한 UFS"는 모호한 표현이므로 무시한다.
→ 명시된 사용률 조건만 사용한다.

SELECT COUNT(*)
FROM nand_health
WHERE storage_utilization <= 0.5;

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

"비트 에러의 평균"
→ AVG(uecc)

"불량 블록의 합계"
→ SUM(rtbb)

"가장 높은 PE Cycle"
→ MAX(pe_cycle)

==================================================
8. UFS 개수와 수치 합계를 구분
==================================================

사용자가 UFS 또는 장치의 개수를 물으면
COUNT(*)를 사용한다.

예:

"불량 블록이 70개 이상인 UFS는 몇 개야?"
→ COUNT(*)

반면:

"비트 에러의 총합은?"
→ SUM(uecc)

"비트 에러가 발생한 UFS는 몇 개야?"
→ COUNT(*)
WHERE uecc > 0

==================================================
9. 그룹별 분석
==================================================

사용자가 "회사별", "제조사별", "벤더별"이라고 하면
GROUP BY vednor를 사용한다.

사용자가 "제품별", "품번별"이라고 하면
GROUP BY pn을 사용한다.

예:

"회사별 UFS 개수"
→
SELECT vednor, COUNT(*) AS unit_count
FROM nand_health
GROUP BY vednor;

"회사별 평균 비트 에러"
→
SELECT vednor, AVG(uecc) AS avg_uecc
FROM nand_health
GROUP BY vednor;

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

"회사별 불량 블록이 가장 많은 순서"
→
GROUP BY vednor
ORDER BY rtbb DESC

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

"불량 블록이 70개 이상이고 비트 에러가 10개 초과"
→
rtbb >= 70
AND uecc > 10

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
- 불량 블록을 rtbb로 매핑했는가?
- 비트 에러/오류를 uecc로 매핑했는가?
- PE Cycle을 pe_cycle로 매핑했는가?
- 전원 급차단을 spocount로 매핑했는가?
- 사용률을 storage_utilization으로 매핑했는가?
- 총 용량/사용 용량을 density/storage_used_already로 정확히 구분했는가?

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


def generate_sql(question: str) -> str:
    """자연어 질문을 nand_health 테이블에 대한 SELECT SQL 문 하나로 변환한다."""

    prompt = _build_sql_prompt(question)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system="너는 정확한 SQL을 생성하는 데이터 분석 전문가다.",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    sql = response.content[0].text.strip()

    sql = sql.replace("```sql", "")
    sql = sql.replace("```", "")
    sql = sql.strip()

    return sql


def summarize_result(question: str, result: "pl.DataFrame") -> str:
    """SQL 실행 결과를 한국어 한두 문장으로 요약한다."""

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

    summary_response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": summary_prompt
            }
        ],
        temperature=0
    )

    return summary_response.content[0].text.strip()


def answer_question(con, question: str) -> dict:
    """
    자연어 질문 하나를 SQL 생성 -> 검증 -> 실행 -> 요약까지 처리하고
    frontend/README.md 에 정의된 것과 같은 형식의 dict를 반환한다.

    frontend/app.py 의 create_demo_result(question) 을
    이 함수 호출로 교체하면 실제 데이터와 연결된다.

    반환 형식:
    {
        "answer": str,                # 한두 문장 요약
        "data": list[dict],           # SQL 실행 결과 (행 단위 dict 리스트)
        "table": str,                 # 조회한 테이블명
        "recognized_columns": list,   # 결과에 포함된 컬럼 목록
        "sql": str,                   # 생성된 SQL
        "validation": str,            # 검증 통과 여부 및 사유
        "chart": dict,                # 시각화 힌트 (현재는 비어있음, 필요 시 규칙 추가)
    }
    """

    sql = generate_sql(question)

    is_valid, error_message = validate_sql(sql)

    if not is_valid:
        return {
            "answer": f"SQL 검증에 실패했습니다: {error_message}",
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": sql,
            "validation": f"실패 - {error_message}",
            "chart": {},
        }

    try:
        result = con.execute(sql).pl()
    except Exception as e:
        return {
            "answer": "SQL 실행 중 오류가 발생했습니다.",
            "data": [],
            "table": ALLOWED_TABLE,
            "recognized_columns": [],
            "sql": sql,
            "validation": f"실행 오류 - {e}",
            "chart": {},
        }

    summary = summarize_result(question, result)

    return {
        "answer": summary,
        "data": result.to_dicts(),
        "table": ALLOWED_TABLE,
        "recognized_columns": result.columns,
        "sql": sql,
        "validation": "통과",
        "chart": {},
    }
