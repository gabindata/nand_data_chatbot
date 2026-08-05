"""
챗봇 정확도 평가 러너.

test_cases.py의 각 (질문, 정답 SQL) 쌍에 대해:
  1. 실제 챗봇 파이프라인(generate_sql_and_chart)으로 SQL을 생성한다.
  2. validate_sql로 검증한다.
  3. 통과하면 실행하고, 정답 SQL 실행 결과와 값 단위로 비교한다.
     (컬럼명/별칭은 강제하지 않으므로 값들의 집합으로만 비교한다.)

사용법:
    python tests/accuracy/run_eval.py [--data PATH] [--limit N] [--out PATH]

--limit N 을 주면 앞에서부터 N개만 돌린다(빠른 스모크 테스트용).
결과는 콘솔 요약 + JSON 파일(tests/accuracy/results/*.json)로 저장된다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "llm_sql"))

import app as llm_app  # noqa: E402
from test_cases import build_test_cases  # noqa: E402

DEFAULT_DATA = REPO_ROOT / "data" / "nand_health_test.csv"


def normalize_row(row: dict) -> tuple:
    """컬럼명/순서에 무관하게 비교할 수 있도록 행의 값들을 정규화한다."""

    def norm(v):
        if isinstance(v, float):
            return round(v, 3)
        if isinstance(v, str):
            return v.strip()
        return v

    normed = [norm(v) for v in row.values()]
    return tuple(sorted(normed, key=lambda x: (str(type(x)), str(x))))


def normalize_result(rows: list[dict]) -> list[tuple]:
    return sorted((normalize_row(r) for r in rows), key=str)


def run_case(con, case: dict) -> dict:
    question = case["question"]
    expected_sql = case["expected_sql"]

    result = {
        "id": case["id"],
        "category": case["category"],
        "question": question,
        "expected_sql": expected_sql,
        "generated_sql": "",
        "outcome": "",  # pass / wrong_result / validation_failed / exec_error / gen_error
        "detail": "",
    }

    # 1. 정답 SQL 실행 (기준값)
    try:
        expected_rows = con.execute(expected_sql).pl().to_dicts()
    except Exception as e:
        result["outcome"] = "expected_sql_error"
        result["detail"] = f"정답 SQL 자체가 실행 안 됨(테스트 케이스 버그): {e}"
        return result

    # 2. 실제 파이프라인으로 SQL 생성
    try:
        schema_str, allowed_cols = llm_app.get_schema(con)
        generated = llm_app.generate_sql_and_chart(question, schema_str)
        sql = generated["sql"]
    except Exception as e:
        result["outcome"] = "gen_error"
        result["detail"] = f"SQL 생성 중 예외: {e}"
        return result

    result["generated_sql"] = sql

    # 3. 검증
    is_valid, err = llm_app.validate_sql(sql, allowed_cols)
    if not is_valid:
        result["outcome"] = "validation_failed"
        result["detail"] = err
        return result

    # 4. 실행 (production과 동일하게 LIMIT 상한 적용)
    exec_sql, _ = llm_app._apply_row_limit(sql)
    try:
        raw = con.execute(exec_sql).pl()
    except Exception as e:
        result["outcome"] = "exec_error"
        result["detail"] = str(e)
        return result

    if llm_app.TOTAL_COUNT_COL in raw.columns:
        actual_rows = raw.drop(llm_app.TOTAL_COUNT_COL).to_dicts()
    else:
        actual_rows = raw.to_dicts()

    # 5. 모호한 질문 케이스: 메시지 텍스트만 확인
    if case["category"] == "모호한 질문":
        text = " ".join(str(v) for row in actual_rows for v in row.values())
        if "명확" in text or "기준" in text:
            result["outcome"] = "pass"
        else:
            result["outcome"] = "wrong_result"
            result["detail"] = f"명확화 메시지가 아님: {actual_rows}"
        return result

    # 6. 정렬 top-N 케이스: 동점(tie)이 LIMIT 경계에 걸리면 어떤 행이
    #    뽑히는지가 SQL 엔진 입장에서 원래 비결정적이다(예: pe_cycle=0인
    #    행이 161개인데 5개만 뽑으면 매번 다른 5개가 나올 수 있음).
    #    그래서 unit_id까지 포함해 행 단위로 비교하면 SQL이 100% 똑같아도
    #    오탐이 난다. 이 카테고리는 정렬 기준 컬럼의 "값 목록"만 비교한다.
    if case["category"] == "정렬":
        sort_col = None
        for col in expected_rows[0].keys() if expected_rows else []:
            if col != "unit_id":
                sort_col = col
                break
        expected_vals = sorted(round(r[sort_col], 3) if isinstance(r[sort_col], float) else r[sort_col] for r in expected_rows)
        actual_vals = sorted(round(r[sort_col], 3) if isinstance(r[sort_col], float) else r[sort_col] for r in actual_rows) if sort_col and actual_rows and sort_col in actual_rows[0] else None
        if len(expected_rows) == len(actual_rows) and expected_vals == actual_vals:
            result["outcome"] = "pass"
        else:
            result["outcome"] = "wrong_result"
            result["detail"] = (
                f"정렬 기준 값 목록 불일치 (동점 외 문제로 보임): "
                f"expected_vals={expected_vals} actual={actual_rows[:5]}"
            )
        return result

    # 7. 값 비교
    if normalize_result(expected_rows) == normalize_result(actual_rows):
        result["outcome"] = "pass"
    else:
        result["outcome"] = "wrong_result"
        result["detail"] = (
            f"expected={expected_rows[:5]}{'...' if len(expected_rows) > 5 else ''} "
            f"actual={actual_rows[:5]}{'...' if len(actual_rows) > 5 else ''}"
        )

    return result


def stratified_sample(cases: list[dict], n: int) -> list[dict]:
    """카테고리별로 최대한 골고루 n개를 뽑는다 (한 카테고리로 쏠리지 않게)."""
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)

    cats = list(by_cat.keys())
    picked: list[dict] = []
    idx = 0
    while len(picked) < n and any(by_cat[cat] for cat in cats):
        cat = cats[idx % len(cats)]
        if by_cat[cat]:
            picked.append(by_cat[cat].pop(0))
        idx += 1
    return picked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sample", type=int, default=None,
                         help="카테고리별로 골고루 N개 뽑아서 실행")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    cases = build_test_cases()
    if args.sample:
        cases = stratified_sample(cases, args.sample)
    elif args.limit:
        cases = cases[: args.limit]

    print(f"데이터 로드: {args.data}")
    con = llm_app.get_duckdb_connection()
    row_count = llm_app.load_into_duckdb(con, args.data)
    print(f"로드 완료: {row_count:,}행")
    print(f"테스트 케이스 {len(cases)}개 실행 시작...\n")

    results = []
    start = time.time()
    for i, case in enumerate(cases, 1):
        t0 = time.time()
        r = run_case(con, case)
        elapsed = time.time() - t0
        results.append(r)
        mark = "OK " if r["outcome"] == "pass" else "FAIL"
        print(f"[{i:3d}/{len(cases)}] {mark} ({elapsed:4.1f}s) [{r['category']}] {case['question']}")
        if r["outcome"] != "pass":
            print(f"           -> {r['outcome']}: {r['detail'][:200]}")

    total_elapsed = time.time() - start

    outcome_counts = Counter(r["outcome"] for r in results)
    total = len(results)
    passed = outcome_counts.get("pass", 0)

    print("\n" + "=" * 60)
    print(f"전체: {total}개 | 통과: {passed}개 | 정확도: {passed/total*100:.1f}%")
    print(f"소요 시간: {total_elapsed:.0f}초")
    print("-" * 60)
    for outcome, cnt in outcome_counts.most_common():
        print(f"  {outcome}: {cnt}개")

    print("\n카테고리별 정확도:")
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, rs in by_cat.items():
        p = sum(1 for r in rs if r["outcome"] == "pass")
        print(f"  {cat}: {p}/{len(rs)} ({p/len(rs)*100:.0f}%)")

    out_dir = REPO_ROOT / "tests" / "accuracy" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else out_dir / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total": total,
                "passed": passed,
                "accuracy": passed / total,
                "elapsed_sec": total_elapsed,
                "outcome_counts": dict(outcome_counts),
                "results": results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\n결과 저장됨: {out_path}")


if __name__ == "__main__":
    main()
