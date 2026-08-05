# tests/accuracy/

챗봇의 "자연어 → SQL → 실행 결과" 파이프라인이 실제로 정확한지
정량적으로 측정하는 평가 세트입니다.

## 구성

- `test_cases.py` — (질문, 정답 SQL) 쌍 102개. `data/nand_health_test.csv`
  스키마(unit_id/pe_cycle/unstable_count/model/capacity_gb/temperature_c/
  error_count/usage_hours) 기준으로 단순 집계, 그룹별 집계, 조건 필터,
  복합 조건, 정렬(top-N), 모호한 질문, 카테고리 값 필터 등 11개
  카테고리를 다룹니다.
- `run_eval.py` — 각 질문을 실제 `llm_sql/app.py`의
  `generate_sql_and_chart()` → `validate_sql()` → 실행 파이프라인에
  그대로 태워서, 결과를 정답 SQL의 실행 결과와 값 단위로 비교합니다.
  (컬럼명/별칭은 챗봇이 자유롭게 정하므로 값 비교만 합니다.)
- `results/` — 실행 결과 JSON (gitignore 처리됨, 커밋 안 됨)

## 실행 방법

```bash
pip install -r llm_sql/requirements.txt   # duckdb, anthropic 등

# 전체 102개
python tests/accuracy/run_eval.py

# 카테고리별로 골고루 N개만 (빠른 확인용)
python tests/accuracy/run_eval.py --sample 20

# 앞에서부터 N개만 (스모크 테스트용, 카테고리가 한쪽으로 쏠릴 수 있음)
python tests/accuracy/run_eval.py --limit 5
```

질문 하나당 Claude API를 1회 호출합니다(요약 단계는 정확도 측정과
무관해 제외). 전체 102개 기준 대략 5~10분, 케이스당 약간의 비용이
듭니다.

## "정렬(top-N)" 카테고리에 대한 주의

`ORDER BY x ASC LIMIT 5`처럼 동점(tie)이 많은 컬럼(예: `pe_cycle=0`인
행이 161개)에서 상위/하위 N개를 뽑으면, SQL이 정답과 완전히 똑같아도
DuckDB가 동점 중 어떤 행을 고르는지는 원래 비결정적입니다. 그래서 이
카테고리는 `unit_id`까지 포함한 행 단위 비교 대신, **정렬 기준
컬럼의 값 목록만** 비교합니다.

## 결과 해석

`outcome` 필드 종류:

- `pass` — 정답과 값이 일치
- `wrong_result` — SQL은 실행됐지만 결과 값이 다름 (로직 오류 가능성)
- `validation_failed` — `validate_sql()`이 거부함 (예: 허용 안 된
  함수/컬럼을 썼거나 다른 테이블명을 씀)
- `exec_error` — DuckDB 실행 자체가 에러
- `gen_error` — Claude API 호출 단계에서 예외 (네트워크/파싱 등)
- `expected_sql_error` — 정답 SQL 자체가 실행이 안 됨 (테스트 케이스
  버그이므로 `test_cases.py`를 고쳐야 함)
