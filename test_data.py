import csv
import random

with open("nand_health_test.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)

    writer.writerow([
        "unit_id",
        "pe_cycle",
        "unstable_count",
        "model",
        "capacity_gb",
        "temperature_c",
        "error_count",
        "usage_hours"
    ])

    for i in range(200000):
        writer.writerow([
            f"UNIT_{i:09d}",
            random.randint(0, 1200),
            random.randint(0, 50),
            random.choice(["A", "B", "C", "D"]),
            random.choice([128, 256, 512, 1024]),
            round(random.uniform(20, 85), 1),
            random.randint(0, 100),
            random.randint(0, 50000)
        ])

print("테스트 파일 생성 완료!")