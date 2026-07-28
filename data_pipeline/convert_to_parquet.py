import duckdb
import sys
import os

# 파일 경로를 실행할 때 입력받기
if len(sys.argv) < 2:
    print("사용법:")
    print("python convert_to_parquet.py 파일경로")
    sys.exit()

input_file = sys.argv[1]

# 확장자 제거 후 Parquet 파일명 생성
base_name = os.path.splitext(input_file)[0]
output_file = base_name + ".parquet"

print(f"입력 파일: {input_file}")
print(f"출력 파일: {output_file}")
print("Parquet 변환 중...")

con = duckdb.connect()

con.execute(f"""
    COPY (
        SELECT *
        FROM read_csv_auto('{input_file}')
    )
    TO '{output_file}'
    (FORMAT PARQUET, COMPRESSION ZSTD);
""")

print("변환 완료!")