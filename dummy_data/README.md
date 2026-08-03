# dummy_data/

성능·용량 테스트용 **가짜 데이터 생성 스크립트** 모음입니다. 실제 서비스
파이프라인(`data_pipeline/`, `backend/upload_server.py`)과는 무관하며,
대용량 업로드 기능이나 쿼리 성능을 확인할 때 필요한 샘플 파일을 만드는
용도로만 씁니다.

## 스크립트 목록

| 파일 | 하는 일 | 결과물 |
| --- | --- | --- |
| `make_csv.py` | 약 100MB 크기의 CSV 더미 데이터를 생성 | `nand_health_100mb.csv` |
| `make_excel.py` | 약 300만 행 규모의 xlsx 더미 데이터를 생성 (`openpyxl` write-only 모드) | `nand_health_300mb.xlsx` |
| `create_parquet.py` | 300만 행을 10만 행 단위 청크로 나눠 parquet 파티션 생성 | `nand_health_parquet/part_XXXX.parquet` |
| `test_data.py` | 20만 행 규모의 소형 CSV 더미 데이터를 생성 | `nand_health_test.csv` |
| `test_parquet.py` | `nand_health_parquet/*.parquet`의 전체 행 수를 세어 출력 (`create_parquet.py` 결과 검증용) | 콘솔 출력 |

## 실행 방법

```bash
pip install -r dummy_data/requirements.txt
python dummy_data/make_csv.py
```

생성된 파일은 이 폴더 기준 상대 경로에 만들어집니다. 만든 더미 파일은
`.gitignore`에 이미 등록된 패턴(`nand_health_100mb.csv`,
`nand_health_300mb.xlsx`, `nand_health_parquet/` 등)이라 커밋되지
않습니다.

## 언제 쓰나

- `frontend/app.py`의 "대용량 파일 업로드 (10GB+)" 흐름을 테스트할 때
  실제로 큰 CSV가 필요한 경우
- `backend/upload_server.py`의 청크 업로드 → parquet 변환 성능을
  확인할 때
- DuckDB 쿼리 응답 속도를 대용량 기준으로 확인하고 싶을 때

실제 팀 데이터를 변환하려면 이 폴더가 아니라 [`data_pipeline/`](../data_pipeline)를 사용하세요.
