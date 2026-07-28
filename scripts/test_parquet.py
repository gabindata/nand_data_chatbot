import duckdb


con = duckdb.connect()


result = con.execute("""
    SELECT COUNT(*)
    FROM read_parquet(
        'nand_health_parquet/*.parquet'
    )
""").fetchone()


print(
    "전체 데이터 개수:",
    result[0]
)