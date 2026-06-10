import json

import typer

from harness.db import Database, now_iso
from harness.schemas.decision import DecisionStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition

STUB_DECISIONS = [
    {
        "category": "data_model",
        "question": "What fields should the entity have?",
        "options": [
            "Minimal (id, name, created_at)",
            "Standard (id, name, description, created_at, updated_at)",
            "Full (id, name, description, metadata, soft_delete, timestamps)",
        ],
        "recommendation": "Standard (id, name, description, created_at, updated_at)",
    },
    {
        "category": "api_contract",
        "question": "Should the API use DTOs or return the entity directly?",
        "options": [
            "Return entity directly",
            "Use DTOs (separate request/response models)",
        ],
        "recommendation": "Use DTOs (separate request/response models)",
    },
    {
        "category": "business_rules",
        "question": "What validation rules apply?",
        "options": [
            "None beyond non-null",
            "Standard non-null + length limits",
            "Full validation with custom messages",
        ],
        "recommendation": "Standard non-null + length limits",
    },
]


def generate_stub_decisions(task: dict, db: Database) -> list[dict]:
    assert_command_allowed("interrogate", TaskStatus(task["status"]))
    transition(task, TaskStatus.INTERROGATING, db)

    decisions = []
    for item in STUB_DECISIONS:
        dec_id = db.new_decision_id(task["id"])
        now = now_iso()
        decision = {
            "id": dec_id,
            "task_id": task["id"],
            "category": item["category"],
            "question": item["question"],
            "options_json": json.dumps(item["options"]),
            "recommendation": item.get("recommendation"),
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


def list_decisions(task_id: str, db: Database) -> list:
    return db.get_decisions(task_id)


def answer_decision(decision_id: str, answer: str, task: dict, db: Database) -> None:
    assert_command_allowed("answer", TaskStatus(task["status"]))
    dec = db.get_decision(decision_id.upper())
    if dec is None:
        typer.echo(f"Error: Decision {decision_id} not found.", err=True)
        raise typer.Exit(1)
    db.update_decision(dec["id"], {
        "selected_answer": answer,
        "status": DecisionStatus.ANSWERED,
        "updated_at": now_iso(),
    })


def _detect_conflicts(decision: dict, memories: list) -> list[dict]:
    """Keyword-scan: warn if a memory lesson appears to contradict selected_answer."""
    answer = (decision.get("selected_answer") or "").lower()
    conflicts = []
    for m in memories:
        try:
            val = json.loads(m["value_json"])
            lesson = (val.get("lesson") or str(val)).lower() if isinstance(val, dict) else str(val).lower()
        except (json.JSONDecodeError, AttributeError):
            continue
        # Simple antonym pairs that signal a potential contradiction
        _ANTONYMS = [
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
        ]
        for memory_word, answer_word in _ANTONYMS:
            if memory_word in lesson and answer_word in answer:
                conflicts.append({
                    "memory_key": m["key"],
                    "warning": (
                        f"Memory '{m['key']}' recommends '{memory_word}' "
                        f"but answer contains '{answer_word}'"
                    ),
                })
                break
    return conflicts


def approve_decisions(
    decision_ids: list[str], task: dict, db: Database
) -> tuple[bool, list[dict]]:
    assert_command_allowed("approve", TaskStatus(task["status"]))
    all_conflicts: list[dict] = []
    memories = db.list_memory()

    for did in decision_ids:
        dec = db.get_decision(did.upper())
        if dec is None:
            typer.echo(f"Error: Decision {did} not found.", err=True)
            raise typer.Exit(1)
        if dec["status"] == DecisionStatus.PENDING:
            typer.echo(
                f"Error: Decision {did} has no answer yet. Run 'harness answer {did}' first.",
                err=True,
            )
            raise typer.Exit(1)
        db.update_decision(dec["id"], {
            "status": DecisionStatus.APPROVED,
            "updated_at": now_iso(),
        })
        all_conflicts.extend(_detect_conflicts(dict(dec), memories))

    pending = db.get_pending_decisions(task["id"])
    if not pending:
        transition(task, TaskStatus.DECISIONS_APPROVED, db)
        return True, all_conflicts
    return False, all_conflicts
