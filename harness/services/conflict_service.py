import json

from pydantic import BaseModel, ValidationError

from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt

_ANTONYM_PAIRS = [
    ("dto", "entity directly"),
    ("entity directly", "dto"),
    ("sync", "async"),
    ("async", "sync"),
    ("soft delete", "hard delete"),
    ("hard delete", "soft delete"),
    ("rest", "graphql"),
    ("graphql", "rest"),
    ("monolith", "microservice"),
    ("microservice", "monolith"),
    ("repository", "active record"),
    ("active record", "repository"),
    ("jwt", "session"),
    ("session", "jwt"),
]


class ConflictResult(BaseModel):
    has_conflict: bool
    conflicting_memory_key: str | None = None
    explanation: str | None = None


def detect_conflicts_fast(decision: dict, memories: list) -> list[dict]:
    """Category-scoped antonym matching (no LLM, used as fallback)."""
    answer = (decision.get("selected_answer") or "").lower()
    category = decision.get("category", "")
    conflicts = []
    for m in memories:
        try:
            val = json.loads(m["value_json"])
            mem_category = val.get("category", "") if isinstance(val, dict) else ""
            # Only compare within the same category to reduce false positives
            if mem_category and mem_category != category:
                continue
            lesson = (val.get("lesson") or val.get("rule") or str(val)).lower() if isinstance(val, dict) else str(val).lower()
        except (json.JSONDecodeError, AttributeError):
            continue
        for mem_word, ans_word in _ANTONYM_PAIRS:
            if mem_word in lesson and ans_word in answer:
                conflicts.append({
                    "memory_key": m["key"],
                    "warning": (
                        f"Memory '{m['key']}' recommends '{mem_word}' "
                        f"but answer contains '{ans_word}'"
                    ),
                })
                break
    return conflicts


def detect_conflicts_llm(
    decision: dict,
    memories: list,
    llm: LLMAdapter,
) -> ConflictResult:
    """LLM-based conflict detection with category-filtered memory context."""
    if not memories:
        return ConflictResult(has_conflict=False)

    category = decision.get("category", "")
    # Filter memories to same category + project_standard / architecture_rule types
    relevant = [
        m for m in memories
        if m.get("type") in ("project_standard", "architecture_rule", "lesson")
        or _memory_category(m) == category
    ]
    if not relevant:
        return ConflictResult(has_conflict=False)

    relevant_text = "\n".join(
        f"[{m['type']}] {m['key']}: {json.loads(m['value_json'])}"
        for m in relevant
    )

    template = load_prompt("conflict_detector")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{category}", category)
    user = user.replace("{question}", decision.get("question", ""))
    user = user.replace("{proposed_answer}", decision.get("selected_answer") or "")
    user = user.replace("{relevant_memories}", relevant_text)

    try:
        raw_response = llm.complete(system, user)
        raw = extract_json_block(raw_response)
        return ConflictResult.model_validate_json(raw)
    except (ValidationError, LLMOutputError, Exception):
        # Graceful fallback: if LLM check fails, use fast method
        fast = detect_conflicts_fast(decision, memories)
        if fast:
            return ConflictResult(
                has_conflict=True,
                conflicting_memory_key=fast[0]["memory_key"],
                explanation=fast[0]["warning"],
            )
        return ConflictResult(has_conflict=False)


def _memory_category(m: dict) -> str:
    """Extract category from memory value_json if present."""
    try:
        val = json.loads(m["value_json"])
        return val.get("category", "") if isinstance(val, dict) else ""
    except (json.JSONDecodeError, AttributeError):
        return ""
