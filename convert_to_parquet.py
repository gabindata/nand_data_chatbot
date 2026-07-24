import polars as pl

input_file = "nand_health_test.csv"
output_file = "nand_health_test.parquet"

print("CSV 파일을 읽는 중...")

data = pl.read_csv(input_file)

print(f"총 {data.height:,}개 행을 읽었습니다.")

print("Parquet 파일로 변환 중...")

data.write_parquet(
    output_file,
    compression="zstd"
)

print("변환 완료!")
print(f"저장 파일: {output_file}")