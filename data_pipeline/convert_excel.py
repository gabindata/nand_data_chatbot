import polars as pl
import os


INPUT_FILE = "uploads/nand_health_sample.xlsx"

OUTPUT_DIR = "converted_parquet"


os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


print(
    "Excel → Parquet 변환 시작..."
)


df = pl.read_excel(
    INPUT_FILE
)


print(
    f"Excel 읽기 완료: {len(df):,}행"
)


OUTPUT_FILE = os.path.join(
    OUTPUT_DIR,
    "part_0001.parquet"
)


df.write_parquet(
    OUTPUT_FILE,
    compression="zstd"
)


print(
    "Parquet 변환 완료!"
)


print(
    f"저장 위치: {OUTPUT_FILE}"
)