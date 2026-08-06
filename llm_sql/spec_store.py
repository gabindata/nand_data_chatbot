"""
질의 명세서 저장소.

챗봇은 기준이 모호한 질문에는 답하지 않고 사용자에게 되묻는다
(llm_sql/app.py 의 "모호한 질문" 규칙). 이때 사용자가 해준 명확화
답변을 여기에 "명세"로 쌓아두고, 이후 SQL 생성 프롬프트에 함께 넣어
같은 표현이 다시 나오면 되묻지 않고 바로 답하게 만든다.

세션(브라우저 탭)마다 새로 뜨는 DuckDB와 달리 명세는 팀이 계속
누적해야 의미가 있으므로 JSON 파일로 영구 보관한다.

제공 함수:
- load_specs(): 저장된 명세 목록 읽기
- add_spec(...): 명세 하나 추가 후 저장
- delete_spec(spec_id): 명세 하나 삭제
- format_specs_for_prompt(specs): 프롬프트에 넣을 문자열로 변환
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 프로젝트 최상위에 둔다. 팀이 함께 쌓아가는 지식이라 커밋 대상이다.
SPEC_FILE = os.path.abspath(os.path.join(BASE_DIR, "..", "query_specs.json"))

# 프롬프트에 넣을 최대 명세 개수. 명세가 계속 쌓여도 토큰이 무한정
# 늘어나지 않도록 최근 것부터 이만큼만 넣는다.
MAX_SPECS_IN_PROMPT = 40


def load_specs(path: str = SPEC_FILE) -> list[dict]:
    """저장된 명세 목록을 읽는다. 파일이 없거나 깨졌으면 빈 목록."""
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 명세가 깨졌다고 챗봇 자체가 죽으면 안 된다. 빈 목록으로 계속 진행.
        return []

    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def save_specs(specs: list[dict], path: str = SPEC_FILE) -> None:
    """명세 목록을 파일에 쓴다."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(specs, f, ensure_ascii=False, indent=2)


def add_spec(
    trigger_question: str,
    clarification: str,
    ambiguous_reason: str = "",
    resolved_sql: str = "",
    path: str = SPEC_FILE,
) -> dict:
    """
    명확화 한 건을 명세로 추가하고 저장한다. 추가된 항목을 반환한다.

    trigger_question: 원래 답변을 보류했던 모호한 질문
    clarification:    사용자가 알려준 기준
    ambiguous_reason: 어떤 점이 모호했는지 (챗봇이 되물을 때 쓴 이유)
    resolved_sql:     명확화 후 실제로 실행된 SQL (있으면 근거로 함께 보관)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = {
        "id": str(uuid.uuid4()),
        "trigger_question": trigger_question,
        "clarification": clarification,
        "ambiguous_reason": ambiguous_reason,
        "resolved_sql": resolved_sql,
        "created_at": now,
        "updated_at": now,
    }

    specs = load_specs(path)
    specs.append(entry)
    save_specs(specs, path)
    return entry


def update_spec(spec_id: str, path: str = SPEC_FILE, **fields) -> list[dict]:
    """
    명세 하나의 필드를 갱신하고 저장한다. 갱신된 전체 목록을 반환한다.
    (예: 명확화 후 실제로 실행된 SQL을 근거로 나중에 붙일 때)
    """
    specs = load_specs(path)
    for entry in specs:
        if entry.get("id") == spec_id:
            entry.update(fields)
            entry["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            break
    save_specs(specs, path)
    return specs


def delete_spec(spec_id: str, path: str = SPEC_FILE) -> bool:
    """명세 하나를 지운다. 실제로 지워졌으면 True."""
    specs = load_specs(path)
    remaining = [entry for entry in specs if entry.get("id") != spec_id]
    if len(remaining) == len(specs):
        return False
    save_specs(remaining, path)
    return True


def format_specs_for_prompt(specs: list[dict]) -> str:
    """
    명세 목록을 SQL 생성 프롬프트에 넣을 문자열로 만든다.
    명세가 없으면 빈 문자열을 반환해서 프롬프트에 섹션 자체가 생기지 않게 한다.
    """
    if not specs:
        return ""

    recent = specs[-MAX_SPECS_IN_PROMPT:]
    lines = []
    for entry in recent:
        question = entry.get("trigger_question", "").strip()
        clarification = entry.get("clarification", "").strip()
        if not question or not clarification:
            continue
        lines.append(f'  - "{question}" → {clarification}')

    if not lines:
        return ""
    return "\n".join(lines)
