from openpyxl import Workbook
import random
import string
import os


OUTPUT_FILE = "nand_health_300mb.xlsx"

TARGET_SIZE = 300 * 1024 * 1024  # 300 MiB


headers = [
    "unit_id",
    "pe_cycle",
    "unstable_count",
    "model",
    "capacity_gb",
    "temperature_c",
    "error_count",
    "usage_hours"
]


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


print("엑셀 파일 생성 시작...")


wb = Workbook(
    write_only=True
)


ws = wb.create_sheet(
    "nand_health"
)


ws.append(headers)


# 약 300만 행 생성
for i in range(1, 3_000_001):

    # 압축이 많이 되지 않도록 고유한 문자열 생성
    unique_text = "".join(
        random.choices(
            string.ascii_letters + string.digits,
            k=120
        )
    )


    ws.append([

        f"NAND_{i:010d}_{unique_text}",

        100 + (i % 901),

        i % 10,

        models[i % 4],

        capacities[i % 4],

        round(
            40 + (i % 500) / 10,
            1
        ),

        i % 20,

        1000 + (i % 50000)

    ])


    if i % 100_000 == 0:

        print(
            f"{i:,}행 생성 완료"
        )


print("엑셀 파일 저장 중...")


wb.save(
    OUTPUT_FILE
)


file_size = os.path.getsize(
    OUTPUT_FILE
)


print(
    f"완료! 파일 크기: "
    f"{file_size / (1024 * 1024):.2f} MB"
)