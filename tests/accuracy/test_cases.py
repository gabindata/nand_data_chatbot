"""
챗봇 정확도 측정용 테스트 케이스 100개 이상.

각 케이스는 (자연어 질문, 정답 SQL) 쌍이다. 정답 SQL은 사람이 직접
작성해 정확성을 보장하고, 자연어 질문은 실제 사용자가 쓸 법한 다양한
표현으로 만든다. data/nand_health_test.csv (20만 행) 스키마를 기준으로
한다:

    unit_id (str, 고유), pe_cycle (int, 0~1200), unstable_count (int, 0~50),
    model (str, A/B/C/D), capacity_gb (int, 128/256/512/1024),
    temperature_c (float, 20~85), error_count (int, 0~100),
    usage_hours (int, 0~50000)

run_eval.py가 각 질문을 실제 챗봇 파이프라인(generate_sql_and_chart)에
넣어 생성된 SQL의 실행 결과를, 여기 적힌 정답 SQL의 실행 결과와
값 단위로 비교한다.
"""

from __future__ import annotations

NUMERIC_COLUMNS = [
    ("pe_cycle", "PE 사이클"),
    ("unstable_count", "불안정 카운트"),
    ("temperature_c", "온도"),
    ("error_count", "에러 개수"),
    ("usage_hours", "사용 시간"),
]

# (자연어 비교 표현, SQL 연산자)
COMPARATORS = [
    ("이상", ">="),
    ("초과", ">"),
    ("이하", "<="),
    ("미만", "<"),
]

# 컬럼별로 실제 분포(중앙값 근처)를 고려해 고른 대표 임계값
THRESHOLDS = {
    "pe_cycle": 600,
    "unstable_count": 25,
    "temperature_c": 50,
    "error_count": 50,
    "usage_hours": 25000,
}

# 두 번째 임계값(필터+SUM 케이스용, 컬럼당 다른 값으로 변화를 줌)
THRESHOLDS_2 = {
    "pe_cycle": 900,
    "unstable_count": 40,
    "temperature_c": 70,
    "error_count": 75,
    "usage_hours": 40000,
}

# 세 번째 임계값(추가 필터 다양성용, 앞의 두 세트와 다른 값)
THRESHOLDS_3 = {
    "pe_cycle": 300,
    "unstable_count": 10,
    "temperature_c": 35,
    "error_count": 20,
    "usage_hours": 10000,
}

# BETWEEN 범위 케이스용 (하한, 상한)
RANGES = {
    "pe_cycle": (400, 800),
    "unstable_count": (10, 30),
    "temperature_c": (40, 65),
    "error_count": (20, 60),
    "usage_hours": (10000, 30000),
}

MODELS = ["A", "B", "C", "D"]
CAPACITIES = [128, 256, 512, 1024]


def _case(id_, category, question, expected_sql, notes=""):
    return {
        "id": id_,
        "category": category,
        "question": question,
        "expected_sql": expected_sql,
        "notes": notes,
    }


def build_test_cases() -> list[dict]:
    cases: list[dict] = []
    n = 0

    def add(category, question, expected_sql, notes=""):
        nonlocal n
        n += 1
        cases.append(_case(f"T{n:03d}", category, question, expected_sql, notes))

    # ------------------------------------------------------------
    # A. 전체 건수
    # ------------------------------------------------------------
    add("전체 집계", "전체 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data")

    # ------------------------------------------------------------
    # A2. 컬럼별 단순 집계 (AVG/SUM/MAX/MIN) — 5 컬럼 x 4 함수 = 20
    # ------------------------------------------------------------
    agg_phrases = [
        ("평균", "AVG"),
        ("합계", "SUM"),
        ("최댓값", "MAX"),
        ("최솟값", "MIN"),
    ]
    for col, label in NUMERIC_COLUMNS:
        for phrase, func in agg_phrases:
            add(
                "단순 집계",
                f"{label}의 {phrase}은 얼마야?",
                f"SELECT {func}({col}) AS result FROM uploaded_data",
            )

    # ------------------------------------------------------------
    # B. model별 그룹 집계 (COUNT 1 + AVG x 5 = 6)
    # ------------------------------------------------------------
    add("그룹 집계", "모델별로 개수를 알려줘",
        "SELECT model, COUNT(*) AS cnt FROM uploaded_data GROUP BY model")
    for col, label in NUMERIC_COLUMNS:
        add(
            "그룹 집계",
            f"모델별 {label} 평균을 보여줘",
            f"SELECT model, AVG({col}) AS avg_val FROM uploaded_data GROUP BY model",
        )

    # ------------------------------------------------------------
    # B2. capacity_gb별 그룹 집계 (COUNT 1 + AVG x 5 = 6)
    # ------------------------------------------------------------
    add("그룹 집계", "용량(capacity_gb)별로 몇 개씩 있는지 알려줘",
        "SELECT capacity_gb, COUNT(*) AS cnt FROM uploaded_data GROUP BY capacity_gb")
    for col, label in NUMERIC_COLUMNS:
        add(
            "그룹 집계",
            f"용량별 {label} 평균이 어떻게 돼?",
            f"SELECT capacity_gb, AVG({col}) AS avg_val FROM uploaded_data GROUP BY capacity_gb",
        )

    # ------------------------------------------------------------
    # C. 필터 + COUNT (4 비교 x 5 컬럼 = 20)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS[col]
        for phrase, op in COMPARATORS:
            add(
                "필터+개수",
                f"{label}이 {threshold} {phrase}인 유닛이 몇 개야?",
                f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE {col} {op} {threshold}",
            )

    # ------------------------------------------------------------
    # C2. 필터 + AVG (2 비교 x 5 컬럼 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS[col]
        for phrase, op in [COMPARATORS[0], COMPARATORS[2]]:  # 이상, 이하
            add(
                "필터+평균",
                f"{label}이 {threshold} {phrase}인 유닛들의 {label} 평균은?",
                f"SELECT AVG({col}) AS avg_val FROM uploaded_data WHERE {col} {op} {threshold}",
            )

    # ------------------------------------------------------------
    # C3. 필터 + SUM (5개, 임계값2 사용)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS_2[col]
        add(
            "필터+합계",
            f"{label}이 {threshold} 이상인 유닛들의 {label} 합계는 얼마야?",
            f"SELECT SUM({col}) AS sum_val FROM uploaded_data WHERE {col} >= {threshold}",
        )

    # ------------------------------------------------------------
    # D. 필터 + 그룹(model)별 COUNT (3 컬럼 x 2 임계값 = 6)
    # ------------------------------------------------------------
    for col, label in [
        ("pe_cycle", "PE 사이클"),
        ("temperature_c", "온도"),
        ("error_count", "에러 개수"),
    ]:
        for thr_set, tag in [(THRESHOLDS, "기본"), (THRESHOLDS_2, "높은")]:
            threshold = thr_set[col]
            add(
                "필터+그룹",
                f"{label}이 {threshold} 이상인 유닛을 모델별로 몇 개씩인지 알려줘",
                f"SELECT model, COUNT(*) AS cnt FROM uploaded_data "
                f"WHERE {col} >= {threshold} GROUP BY model",
                notes=tag,
            )

    # ------------------------------------------------------------
    # E. 정렬 top-N (5 컬럼 x 높은순/낮은순 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "정렬",
            f"{label}이 가장 높은 유닛 5개를 unit_id랑 같이 보여줘",
            f"SELECT unit_id, {col} FROM uploaded_data ORDER BY {col} DESC LIMIT 5",
        )
        add(
            "정렬",
            f"{label}이 가장 낮은 유닛 5개를 unit_id랑 같이 보여줘",
            f"SELECT unit_id, {col} FROM uploaded_data ORDER BY {col} ASC LIMIT 5",
        )

    # ------------------------------------------------------------
    # F. 복합 조건 (AND) — 5개
    # ------------------------------------------------------------
    add(
        "복합조건",
        "PE 사이클이 600 이상이고 온도가 50 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE pe_cycle >= 600 AND temperature_c >= 50",
    )
    add(
        "복합조건",
        "에러 개수가 50 이상이고 사용 시간이 25000 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE error_count >= 50 AND usage_hours >= 25000",
    )
    add(
        "복합조건",
        "불안정 카운트가 25 이상이고 온도가 70 이하인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE unstable_count >= 25 AND temperature_c <= 70",
    )
    add(
        "복합조건",
        "모델이 A이고 PE 사이클이 600 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE model = 'A' AND pe_cycle >= 600",
    )
    add(
        "복합조건",
        "용량이 1024이고 온도가 50 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE capacity_gb = 1024 AND temperature_c >= 50",
    )

    # ------------------------------------------------------------
    # G. 모호한 질문 (기준 불명확 메시지가 나와야 함) — 5개
    # ------------------------------------------------------------
    ambiguous_questions = [
        "불량 유닛 찾아줘",
        "위험한 유닛 알려줘",
        "상태 안 좋은 유닛 보여줘",
        "문제 있는 데이터 찾아줘",
        "이상한 유닛들 좀 봐줘",
    ]
    for q in ambiguous_questions:
        add(
            "모호한 질문",
            q,
            "SELECT '질문의 기준이 명확하지 않습니다.' AS message",
            notes="구체적 기준 없음 → 명확화 메시지가 기대됨",
        )

    # ------------------------------------------------------------
    # H. 카테고리 값 필터 — model 4개 + capacity_gb 4개 = 8
    # ------------------------------------------------------------
    for m in MODELS:
        add(
            "카테고리 필터",
            f"모델이 {m}인 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE model = '{m}'",
        )
    for c in CAPACITIES:
        add(
            "카테고리 필터",
            f"용량이 {c}GB인 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE capacity_gb = {c}",
        )

    # ------------------------------------------------------------
    # I. 복합 집계 — 한 질문에 여러 통계 함께 요청 (5 컬럼 x 3 조합 = 15)
    # ------------------------------------------------------------
    agg_pairs = [
        ("평균", "AVG", "최댓값", "MAX"),
        ("평균", "AVG", "최솟값", "MIN"),
        ("최댓값", "MAX", "최솟값", "MIN"),
    ]
    for col, label in NUMERIC_COLUMNS:
        for p1, f1, p2, f2 in agg_pairs:
            add(
                "복합집계",
                f"{label}의 {p1}이랑 {p2}을 같이 알려줘",
                f"SELECT {f1}({col}) AS val1, {f2}({col}) AS val2 FROM uploaded_data",
            )

    # ------------------------------------------------------------
    # J. 다중 그룹(model + capacity_gb) — COUNT 1 + AVG 5 = 6
    # ------------------------------------------------------------
    add(
        "다중그룹",
        "모델별, 용량별로 개수를 알려줘",
        "SELECT model, capacity_gb, COUNT(*) AS cnt FROM uploaded_data "
        "GROUP BY model, capacity_gb",
    )
    for col, label in NUMERIC_COLUMNS:
        add(
            "다중그룹",
            f"모델별, 용량별 {label} 평균을 보여줘",
            f"SELECT model, capacity_gb, AVG({col}) AS avg_val FROM uploaded_data "
            f"GROUP BY model, capacity_gb",
        )

    # ------------------------------------------------------------
    # K. HAVING — 그룹 집계 후 조건 필터 (5개)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS[col]
        add(
            "HAVING",
            f"{label} 평균이 {threshold} 이상인 모델만 보여줘",
            f"SELECT model, AVG({col}) AS avg_val FROM uploaded_data "
            f"GROUP BY model HAVING AVG({col}) >= {threshold}",
        )

    # ------------------------------------------------------------
    # L. BETWEEN 범위 — 5개
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        lo, hi = RANGES[col]
        add(
            "범위조건",
            f"{label}이 {lo}에서 {hi} 사이인 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data "
            f"WHERE {col} BETWEEN {lo} AND {hi}",
        )

    # ------------------------------------------------------------
    # M. 부정 조건 — model 4개 + capacity_gb 4개 = 8
    # ------------------------------------------------------------
    for m in MODELS:
        add(
            "부정조건",
            f"모델이 {m}이 아닌 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE model != '{m}'",
        )
    for c in CAPACITIES:
        add(
            "부정조건",
            f"용량이 {c}GB가 아닌 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE capacity_gb != {c}",
        )

    # ------------------------------------------------------------
    # N. OR 복합조건 — 6개
    # ------------------------------------------------------------
    or_model_pairs = [("A", "B"), ("C", "D"), ("A", "D")]
    for m1, m2 in or_model_pairs:
        add(
            "OR조건",
            f"모델이 {m1}이거나 {m2}인 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data "
            f"WHERE model = '{m1}' OR model = '{m2}'",
        )
    or_capacity_pairs = [(128, 256), (512, 1024), (128, 1024)]
    for c1, c2 in or_capacity_pairs:
        add(
            "OR조건",
            f"용량이 {c1}GB이거나 {c2}GB인 유닛이 몇 개야?",
            f"SELECT COUNT(*) AS cnt FROM uploaded_data "
            f"WHERE capacity_gb = {c1} OR capacity_gb = {c2}",
        )

    # ------------------------------------------------------------
    # O. 3중 AND 복합조건 — 4개
    # ------------------------------------------------------------
    add(
        "3중복합조건",
        "PE 사이클이 600 이상이고 온도가 50 이상이고 에러 개수가 50 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE pe_cycle >= 600 AND temperature_c >= 50 AND error_count >= 50",
    )
    add(
        "3중복합조건",
        "모델이 A이고 용량이 1024이고 PE 사이클이 600 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE model = 'A' AND capacity_gb = 1024 AND pe_cycle >= 600",
    )
    add(
        "3중복합조건",
        "불안정 카운트가 25 이상이고 사용 시간이 25000 이상이고 온도가 50 이상인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE unstable_count >= 25 AND usage_hours >= 25000 AND temperature_c >= 50",
    )
    add(
        "3중복합조건",
        "모델이 B이고 에러 개수가 50 이하이고 온도가 70 이하인 유닛이 몇 개야?",
        "SELECT COUNT(*) AS cnt FROM uploaded_data "
        "WHERE model = 'B' AND error_count <= 50 AND temperature_c <= 70",
    )

    # ------------------------------------------------------------
    # P. DISTINCT — 2개
    # ------------------------------------------------------------
    add(
        "DISTINCT",
        "모델이 몇 가지 종류가 있어?",
        "SELECT COUNT(DISTINCT model) AS cnt FROM uploaded_data",
    )
    add(
        "DISTINCT",
        "용량 종류가 몇 가지야?",
        "SELECT COUNT(DISTINCT capacity_gb) AS cnt FROM uploaded_data",
    )

    # ------------------------------------------------------------
    # Q. 비율/퍼센트 — 5개
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS[col]
        add(
            "비율",
            f"{label}이 {threshold} 이상인 유닛의 비율은 몇 퍼센트야?",
            f"SELECT ROUND(COUNT(CASE WHEN {col} >= {threshold} THEN 1 END) * 100.0 "
            f"/ COUNT(*), 2) AS pct FROM uploaded_data",
        )

    # ------------------------------------------------------------
    # R. 추가 임계값 필터+개수 (THRESHOLDS_3, 5 컬럼 x 4 비교 = 20)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS_3[col]
        for phrase, op in COMPARATORS:
            add(
                "필터+개수",
                f"{label}이 {threshold} {phrase}인 유닛 개수는?",
                f"SELECT COUNT(*) AS cnt FROM uploaded_data WHERE {col} {op} {threshold}",
                notes="세 번째 임계값 세트",
            )

    # ------------------------------------------------------------
    # S. 추가 정렬 — top3 내림차순 + top10 오름차순 (5 컬럼 x 2 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "정렬",
            f"{label} 상위 3개 유닛을 unit_id랑 같이 보여줘",
            f"SELECT unit_id, {col} FROM uploaded_data ORDER BY {col} DESC LIMIT 3",
        )
        add(
            "정렬",
            f"{label} 하위 10개 유닛을 unit_id랑 같이 보여줘",
            f"SELECT unit_id, {col} FROM uploaded_data ORDER BY {col} ASC LIMIT 10",
        )

    # ------------------------------------------------------------
    # T. 모델별 추가 집계 (MAX, SUM — 5 컬럼 x 2 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "그룹 집계",
            f"모델별 {label} 최댓값을 알려줘",
            f"SELECT model, MAX({col}) AS max_val FROM uploaded_data GROUP BY model",
        )
        add(
            "그룹 집계",
            f"모델별 {label} 합계를 알려줘",
            f"SELECT model, SUM({col}) AS sum_val FROM uploaded_data GROUP BY model",
        )

    # ------------------------------------------------------------
    # U. 용량별 추가 집계 (MAX, SUM — 5 컬럼 x 2 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "그룹 집계",
            f"용량별 {label} 최댓값을 알려줘",
            f"SELECT capacity_gb, MAX({col}) AS max_val FROM uploaded_data GROUP BY capacity_gb",
        )
        add(
            "그룹 집계",
            f"용량별 {label} 합계를 알려줘",
            f"SELECT capacity_gb, SUM({col}) AS sum_val FROM uploaded_data GROUP BY capacity_gb",
        )

    # ------------------------------------------------------------
    # V. 추가 필터+평균 (THRESHOLDS_3, 이상/이하 — 5 컬럼 x 2 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS_3[col]
        for phrase, op in [COMPARATORS[0], COMPARATORS[2]]:  # 이상, 이하
            add(
                "필터+평균",
                f"{label}이 {threshold} {phrase}인 유닛들의 {label} 평균은 얼마야?",
                f"SELECT AVG({col}) AS avg_val FROM uploaded_data WHERE {col} {op} {threshold}",
                notes="세 번째 임계값 세트",
            )

    # ------------------------------------------------------------
    # W. 추가 필터+합계 (THRESHOLDS 사용 — 5개)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        threshold = THRESHOLDS[col]
        add(
            "필터+합계",
            f"{label}이 {threshold} 이하인 유닛들의 {label} 합계는?",
            f"SELECT SUM({col}) AS sum_val FROM uploaded_data WHERE {col} <= {threshold}",
        )

    # ------------------------------------------------------------
    # X. model x capacity_gb 조합 필터 — 4 x 4 = 16
    # ------------------------------------------------------------
    for m in MODELS:
        for c in CAPACITIES:
            add(
                "카테고리 필터",
                f"모델이 {m}이고 용량이 {c}GB인 유닛이 몇 개야?",
                f"SELECT COUNT(*) AS cnt FROM uploaded_data "
                f"WHERE model = '{m}' AND capacity_gb = {c}",
            )

    # ------------------------------------------------------------
    # Y. 추가 모호한 질문 — 10개
    # ------------------------------------------------------------
    more_ambiguous_questions = [
        "이상 징후 있는 유닛 알려줘",
        "품질 나쁜 유닛 찾아줘",
        "오래된 유닛 보여줘",
        "성능 나쁜 유닛이 몇 개야?",
        "정상 유닛만 보여줘",
        "교체가 필요한 유닛 알려줘",
        "수명이 다한 유닛 찾아줘",
        "심각한 유닛들 좀 봐줘",
        "믿을 수 없는 유닛 알려줘",
        "쓸만한 유닛 개수는?",
    ]
    for q in more_ambiguous_questions:
        add(
            "모호한 질문",
            q,
            "SELECT '질문의 기준이 명확하지 않습니다.' AS message",
            notes="구체적 기준 없음 → 명확화 메시지가 기대됨",
        )

    # ------------------------------------------------------------
    # Z. 단순 집계 패러프레이즈 다양화 — 5 컬럼 x 2 표현 = 10
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "단순 집계",
            f"{label} 평균이 어떻게 돼?",
            f"SELECT AVG({col}) AS result FROM uploaded_data",
            notes="평균 패러프레이즈",
        )
        add(
            "단순 집계",
            f"{label}이 가장 높은 값은 얼마야?",
            f"SELECT MAX({col}) AS result FROM uploaded_data",
            notes="최댓값 패러프레이즈",
        )

    # ------------------------------------------------------------
    # AA. model 필터 + 평균 (2 컬럼 x 4 모델 = 8)
    # ------------------------------------------------------------
    for col, label in [("pe_cycle", "PE 사이클"), ("temperature_c", "온도")]:
        for m in MODELS:
            add(
                "필터+평균",
                f"모델이 {m}인 유닛들의 {label} 평균은?",
                f"SELECT AVG({col}) AS avg_val FROM uploaded_data WHERE model = '{m}'",
                notes="모델 필터",
            )

    # ------------------------------------------------------------
    # BB. capacity_gb 필터 + 평균 (2 컬럼 x 4 용량 = 8)
    # ------------------------------------------------------------
    for col, label in [("error_count", "에러 개수"), ("usage_hours", "사용 시간")]:
        for c in CAPACITIES:
            add(
                "필터+평균",
                f"용량이 {c}GB인 유닛들의 {label} 평균은?",
                f"SELECT AVG({col}) AS avg_val FROM uploaded_data WHERE capacity_gb = {c}",
                notes="용량 필터",
            )

    # ------------------------------------------------------------
    # CC. 전체 개수 동의어 표현 — 5개
    # ------------------------------------------------------------
    total_count_paraphrases = [
        "데이터가 총 몇 건이야?",
        "전체 행 수가 몇 개야?",
        "총 몇 대야?",
        "유닛 총 개수 알려줘",
        "데이터 전체 크기가 어떻게 돼?",
    ]
    for q in total_count_paraphrases:
        add(
            "전체 집계",
            q,
            "SELECT COUNT(*) AS cnt FROM uploaded_data",
            notes="전체 개수 패러프레이즈",
        )

    # ------------------------------------------------------------
    # DD. 모델별 최솟값 + 용량별 최솟값 (5 컬럼 x 2 = 10)
    # ------------------------------------------------------------
    for col, label in NUMERIC_COLUMNS:
        add(
            "그룹 집계",
            f"모델별 {label} 최솟값을 알려줘",
            f"SELECT model, MIN({col}) AS min_val FROM uploaded_data GROUP BY model",
        )
        add(
            "그룹 집계",
            f"용량별 {label} 최솟값을 알려줘",
            f"SELECT capacity_gb, MIN({col}) AS min_val FROM uploaded_data GROUP BY capacity_gb",
        )

    return cases


if __name__ == "__main__":
    cases = build_test_cases()
    print(f"총 {len(cases)}개 테스트 케이스 생성됨")
    from collections import Counter

    counts = Counter(c["category"] for c in cases)
    for cat, cnt in counts.items():
        print(f"  {cat}: {cnt}개")
