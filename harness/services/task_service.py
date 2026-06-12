import json

from harness.db import Database, now_iso
from harness.schemas.decision import DecisionStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


def run_interrogate(task: dict, llm, db: Database, harness_dir=None, config=None) -> list[dict]:
    from pathlib import Path

    from pydantic import ValidationError

    from harness.llm import LLMOutputError, extract_json_block, load_prompt
    from harness.schemas.decision import DecisionMap

    assert_command_allowed("interrogate", TaskStatus(task["status"]))

    from harness.services.memory_service import inject_project_memory
    memory_text = inject_project_memory(db)

    from harness.services.scanner_service import build_codebase_context
    extra_files = config.context_extra_files if config else []
    max_depth = config.context_max_depth if config else 4
    harness_path = Path(harness_dir) if harness_dir else None
    ctx = build_codebase_context(harness_path, extra_files, max_depth) if harness_path else ""
    codebase_text = ctx if ctx else "(no existing codebase)"

    template = load_prompt("interrogator")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{requirement}", task["raw_requirement"])
    user = user.replace("{project_memory}", memory_text)
    user = user.replace("{codebase_context}", codebase_text)

    # Make LLM call and parse BEFORE transitioning state, so a failure
    # doesn't leave the task stuck in INTERROGATING.
    raw_response = llm.complete(system, user)
    raw = extract_json_block(raw_response)

    try:
        decision_map = DecisionMap.model_validate_json(raw)
    except ValidationError as e:
        raise LLMOutputError(f"LLM returned invalid DecisionMap: {e}") from e

    # All data is valid — now commit the state transition.
    transition(task, TaskStatus.INTERROGATING, db)

    decisions = []
    for item in decision_map.decisions:
        dec_id = db.new_decision_id(task["id"])
        now = now_iso()
        decision = {
            "id": dec_id,
            "task_id": task["id"],
            "category": item.category,
            "question": item.question,
            "options_json": json.dumps(item.options),
            "recommendation": item.recommendation,
            "selected_answer": None,
            "status": DecisionStatus.PENDING,
            "created_at": now,
            "updated_at": now,
        }
        db.create_decision(decision)
        decisions.append(decision)

    interrogating = {"id": task["id"], "status": TaskStatus.INTERROGATING}
    transition(interrogating, TaskStatus.WAITING_FOR_DECISIONS, db)
    return decisions


def create_task(requirement: str, db: Database) -> dict:
    if db.get_active_task() is not None:
        active = db.get_active_task()
        raise ValueError(
            f"Active task {active['id']} exists (status: {active['status']}). Complete it first."
        )
    task_id = Database.new_task_id()
    now = now_iso()
    task = {
        "id": task_id,
        "title": requirement[:80],
        "raw_requirement": requirement,
        "status": TaskStatus.INTAKE,
        "created_at": now,
        "updated_at": now,
    }
    db.create_task(task)
    return dict(db.get_task(task_id))


