import json
import re

from pydantic import BaseModel, ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed


class _MemoryItem(BaseModel):
    category: str
    lesson: str
    context: str


class _MemoryWriterOutput(BaseModel):
    memories: list[_MemoryItem]


def _slugify(text: str) -> str:
    """Convert text to a short snake_case key."""
    text = text.lower()[:60]
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def inject_project_memory(db: Database, scope: str | None = None) -> str:
    """Return formatted memory string for injection into prompts."""
    memories = db.list_memory(scope_filter=scope)
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
        entry = {
            "id": Database.new_memory_id(),
            "type": mem.category,
            "scope": config.project_name,
            "key": _slugify(mem.lesson),
            "value_json": json.dumps({"lesson": mem.lesson, "context": mem.context}),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        db.upsert_memory(entry)
        saved.append(entry)

    return saved
