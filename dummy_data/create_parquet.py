import polars as pl
import random
import string
import os


OUTPUT_DIR = "nand_health_parquet"

TOTAL_ROWS = 3_000_000
CHUNK_ROWS = 100_000


models = [
    "Model_A",
    "Model_B",
    "Model_C",
    "Model_D"
]


capacities = [
    128,
    256,
    512,
    1024
]


os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


print("Parquet 파일 생성 시작...")


for start in range(
    1,
    TOTAL_ROWS + 1,
    CHUNK_ROWS
):

    end = min(
        start + CHUNK_ROWS,
        TOTAL_ROWS + 1
    )


    rows = []


    for i in range(
        start,
        end
    ):

        unique_text = "".join(
            random.choices(
                string.ascii_letters
                + string.digits,
                k=120
            )
        )


        rows.append({

            "unit_id":
                f"NAND_{i:010d}_{unique_text}",

            "pe_cycle":
                100 + (i % 901),

            "unstable_count":
                i % 10,

            "model":
                models[i % 4],

            "capacity_gb":
                capacities[i % 4],

            "temperature_c":
                round(
                    40 + (i % 500) / 10,
                    1
                ),

            "error_count":
                i % 20,

            "usage_hours":
                1000 + (i % 50000)

        })


    df = pl.DataFrame(
        rows
    )


    part_number = (
        (start - 1)
        // CHUNK_ROWS
        + 1
    )


    output_file = os.path.join(
        OUTPUT_DIR,
        f"part_{part_number:04d}.parquet"
    )


    df.write_parquet(
        output_file,
        compression="zstd"
    )


    print(
        f"{end - 1:,}행 완료 → "
        f"{output_file}"
    )


print(
    "\n🎉 전체 Parquet 생성 완료!"
)