import csv
import random
import os

OUTPUT_FILE = "nand_health_100mb.csv"

models = ["Model_A", "Model_B", "Model_C", "Model_D"]
capacities = [64, 128, 256, 512]

target_size = 100 * 1024 * 1024  # 100MB

rows = 0

with open(
    OUTPUT_FILE,
    "w",
    newline="",
    encoding="utf-8"
) as file:

    writer = csv.writer(file)

    writer.writerow([
        "unit_id",
        "model",
        "capacity_gb",
        "temperature_c",
        "pe_cycle",
        "unstable_count",
        "error_count",
        "usage_hours"
    ])

    while True:

        writer.writerow([
            f"NAND_{rows:08d}",
            random.choice(models),
            random.choice(capacities),
            round(random.uniform(40, 90), 1),
            random.randint(0, 1000),
            random.randint(0, 10),
            random.randint(0, 20),
            random.randint(0, 20000)
        ])

        rows += 1

        if rows % 100000 == 0:

            current_size = os.path.getsize(
                OUTPUT_FILE
            )

            print(
                f"{rows:,}행 생성 | "
                f"{current_size / (1024 * 1024):.1f}MB"
            )

            if current_size >= target_size:

                break

print()
print("CSV 더미 생성 완료")
print(f"총 행 수: {rows:,}")
print(
    f"파일 크기: "
    f"{os.path.getsize(OUTPUT_FILE) / (1024 * 1024):.1f}MB"
)