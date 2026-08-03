# data_pipeline/

**실제 원본 데이터 파일**(엑셀/CSV)을 챗봇이 읽을 수 있는 parquet으로
변환하는 CLI 스크립트입니다. 가짜 데이터를 만드는
[`dummy_data/`](../dummy_data)와는 목적이 다릅니다.

## 스크립트 목록

| 파일 | 하는 일 |
| --- | --- |
| `convert_excel.py` | `uploads/nand_health_sample.xlsx`를 읽어 `converted_parquet/part_0001.parquet`으로 저장 |
| `convert_to_parquet.py` | 임의의 CSV 파일 경로를 인자로 받아 같은 이름의 `.parquet`으로 변환 (DuckDB `COPY ... TO ... (FORMAT PARQUET)`) |

## 실행 방법

```bash
pip install -r data_pipeline/requirements.txt

# CSV 파일 하나를 parquet으로 변환
python data_pipeline/convert_to_parquet.py path/to/nand_health.csv

# uploads/nand_health_sample.xlsx 를 parquet으로 변환
python data_pipeline/convert_excel.py
```

## backend/upload_server.py 와의 관계

`backend/upload_server.py`는 프론트엔드의 "대용량 파일 업로드" 기능을
통해 들어온 **CSV**를 자동으로 parquet으로 변환합니다(청크 업로드 →
`polars.scan_csv().sink_parquet()`). 즉 CSV → parquet 변환은 이제 그
경로로도 가능합니다.

이 폴더는 다음 경우에 씁니다.

- 서버를 띄우지 않고 터미널에서 즉석으로 파일 하나만 변환하고 싶을 때
- **엑셀(xlsx) 원본**을 변환해야 할 때 — `backend/upload_server.py`는
  CSV만 지원하므로 엑셀 원본은 `convert_excel.py`로 먼저 parquet을
  만들어야 합니다.
