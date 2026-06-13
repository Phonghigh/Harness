import json
import re

from pydantic import BaseModel, ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt
from harness.schemas.decision import MEMORY_TYPES
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed


class _MemoryItem(BaseModel):
    type: str       # one of MEMORY_TYPES
    category: str   # one of DECISION_CATEGORIES — used for scoped injection
    lesson: str
    context: str


class _MemoryWriterOutput(BaseModel):
    memories: list[_MemoryItem]


def _slugify(text: str) -> str:
    """Convert text to a short snake_case key."""
    text = text.lower()[:60]
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def inject_project_memory(
    db: Database,
    scope: str | None = None,
    category: str | None = None,
) -> str:
    """Return formatted memory string for injection into prompts, tracking usage.

    When category is provided, injects memories matching that category PLUS all
    project_standard and architecture_rule entries (always relevant). This avoids
    injecting unrelated memories (e.g. testing patterns into data_model decisions).
    When category is None, all memories are returned (legacy / interrogation use).
    """
    if category:
        anchors = db.list_memory(type_filter="project_standard", scope_filter=scope)
        anchors += db.list_memory(type_filter="architecture_rule", scope_filter=scope)
        scoped = db.list_memory(category_filter=category, scope_filter=scope)
        seen_ids = {m["id"] for m in anchors}
        memories = list(anchors) + [m for m in scoped if m["id"] not in seen_ids]
    else:
        memories = db.list_memory(scope_filter=scope)
    for m in memories:
        db.increment_memory_applied(m["id"])
    return "\n".join(
        f"[{m['type']}] {m['key']}: {json.loads(m['value_json'])}"
        for m in memories
    ) or "(none)"


def search_memory(
    db: Database,
    query: str,
    type_filter: str | None = None,
    scope_filter: str | None = None,
) -> list:
    """Return memories whose key or value_json contain query (case-insensitive)."""
    rows = db.list_memory(type_filter=type_filter, scope_filter=scope_filter)
    q = query.lower()
    return [
        r for r in rows
        if q in r["key"].lower() or q in r["value_json"].lower()
    ]


def write_event_memory(event_type: str, data: dict, db: Database, config) -> None:
    """Write a structured memory entry at a lifecycle event without an LLM call.

    event_type is one of: conflict_override, compliance_failure, compliance_success.
    data contains the fields needed to compose the memory entry.
    """
    now = now_iso()
    scope = config.project_name if config else "default"

    if event_type == "conflict_override":
        mem_type = "feedback"
        category = data.get("category", "")
        key = _slugify(f"conflict_override_{data.get('decision_id', '')}_{data.get('memory_key', '')}")
        lesson = (
            f"Conflict with memory '{data.get('memory_key', '')}' detected but decision "
            f"'{data.get('decision_id', '')}' approved anyway for {category}"
        )
        context = f"Explanation: {data.get('explanation', '')}. Task: {data.get('task_title', '')}"

    elif event_type == "compliance_failure":
        mem_type = "compliance_pattern"
        category = data.get("violation_type", "")
        key = _slugify(f"violation_{data.get('violation_type', '')}_{data.get('contract_id', '')}")
        lesson = f"Patch failed compliance: {data.get('description', '')}"
        context = f"Contract {data.get('contract_id', '')}, violation type: {data.get('violation_type', '')}"

    elif event_type == "compliance_success":
        mem_type = "lesson"
        category = data.get("category", "implementation_scope")
        key = _slugify(f"first_pass_success_{data.get('task_id', '')}")
        lesson = f"Contract for task '{data.get('task_title', '')}' passed compliance on first try"
        context = "Indicates well-formed contract and implementation; reuse this pattern"

    else:
        return

    entry = {
        "id": Database.new_memory_id(),
        "type": mem_type,
        "scope": scope,
        "key": key,
        "value_json": json.dumps({"lesson": lesson, "context": context}),
        "category": category,
        "source_task_id": data.get("task_id"),
        "applied_count": 0,
        "last_applied_at": None,
        "created_at": now,
        "updated_at": now,
    }
    db.upsert_memory(entry)


def write_memory(task: dict, llm: LLMAdapter, db: Database, config) -> list[dict]:
    assert_command_allowed("remember", TaskStatus(task["status"]))

    decisions = db.get_decisions(task["id"])
    decisions_data = [
        {
            "id": d["id"],
            "category": d["category"],
            "question": d["question"],
            "selected_answer": d["selected_answer"],
        }
        for d in decisions
    ]

    contract = db.get_latest_contract(task["id"])
    contract_summary = contract["scope"] if contract else "(no contract)"

    existing = db.list_memory(scope_filter=config.project_name)
    existing_text = "\n".join(
        f"[{m['type']}] {m['key']}: {json.loads(m['value_json'])}"
        for m in existing
    ) or "(none)"

    template = load_prompt("memory_writer")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{requirement}", task["raw_requirement"])
    user = user.replace("{decisions_json}", json.dumps(decisions_data, indent=2))
    user = user.replace("{contract_summary}", contract_summary)
    user = user.replace("{existing_memories}", existing_text)

    raw_response = llm.complete(system, user)
    raw = extract_json_block(raw_response)

    try:
        result = _MemoryWriterOutput.model_validate_json(raw)
    except ValidationError as e:
        raise LLMOutputError(f"LLM returned invalid memory output: {e}") from e

    saved = []
    for mem in result.memories:
        now = now_iso()
        mem_type = mem.type if mem.type in MEMORY_TYPES else "lesson"
        entry = {
            "id": Database.new_memory_id(),
            "type": mem_type,
            "scope": config.project_name,
            "key": _slugify(mem.lesson),
            "value_json": json.dumps({"lesson": mem.lesson, "context": mem.context}),
            "category": mem.category,
            "source_task_id": task["id"],
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now,
            "updated_at": now,
        }
        db.upsert_memory(entry)
        saved.append(entry)

    return saved
