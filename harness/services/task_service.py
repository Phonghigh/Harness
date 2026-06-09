import json

import typer
from pydantic import ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, extract_json_block, load_prompt, split_prompt
from harness.schemas.decision import DecisionMap, DecisionStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


def create_task(requirement: str, db: Database) -> dict:
    if db.get_active_task() is not None:
        active = db.get_active_task()
        raise typer.BadParameter(
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


def get_active_task_or_exit(db: Database) -> dict:
    task = db.get_active_task()
    if task is None:
        typer.echo("Error: No active task. Run 'harness start \"requirement\"' first.", err=True)
        raise typer.Exit(1)
    return dict(task)


def run_interrogate(
    task: dict,
    llm: LLMAdapter,
    db: Database,
    project_memory: str = "[none]",
) -> list[dict]:
    assert_command_allowed("interrogate", TaskStatus(task["status"]))
    transition(task, TaskStatus.INTERROGATING, db)

    template = load_prompt("interrogator")
    system, user_template = split_prompt(template)
    user = user_template.replace("{requirement}", task["raw_requirement"]).replace(
        "{project_memory}", project_memory
    )

    response = llm.complete(system, user)
    raw = extract_json_block(response.content)
    try:
        decision_map = DecisionMap.model_validate_json(raw)
    except (ValidationError, ValueError) as e:
        raise RuntimeError(f"LLM returned invalid DecisionMap: {e}") from e

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
