import json

from pydantic import BaseModel

from harness.db import Database, now_iso
from harness.schemas.decision import DecisionStatus
from harness.schemas.task import TaskStatus
from harness.services.conflict_service import ConflictResult, detect_conflicts_fast, detect_conflicts_llm
from harness.state_machine import assert_command_allowed, transition


class _DecisionAnswer(BaseModel):
    selected_answer: str
    confidence: str  # "high" | "medium" | "low"
    rationale: str

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
        raise ValueError(f"Decision {decision_id} not found.")
    db.update_decision(dec["id"], {
        "selected_answer": answer,
        "status": DecisionStatus.ANSWERED,
        "updated_at": now_iso(),
    })


def approve_decisions(
    decision_ids: list[str],
    task: dict,
    db: Database,
    llm=None,
) -> tuple[bool, list[dict]]:
    assert_command_allowed("approve", TaskStatus(task["status"]))
    all_conflicts: list[dict] = []
    memories = db.list_memory()

    for did in decision_ids:
        dec = db.get_decision(did.upper())
        if dec is None:
            raise ValueError(f"Decision {did} not found.")
        if dec["status"] == DecisionStatus.PENDING:
            raise ValueError(f"Decision {did} has no answer yet. Run 'harness answer {did}' first.")
        db.update_decision(dec["id"], {
            "status": DecisionStatus.APPROVED,
            "updated_at": now_iso(),
        })

        if llm is not None:
            result: ConflictResult = detect_conflicts_llm(dict(dec), memories, llm)
            if result.has_conflict:
                all_conflicts.append({
                    "memory_key": result.conflicting_memory_key or "",
                    "warning": result.explanation or "Conflict detected",
                })
        else:
            all_conflicts.extend(detect_conflicts_fast(dict(dec), memories))

    pending = db.get_pending_decisions(task["id"])
    if not pending:
        transition(task, TaskStatus.DECISIONS_APPROVED, db)
        return True, all_conflicts
    return False, all_conflicts


def auto_answer_decisions(task: dict, decisions: list, llm, db: Database) -> list[dict]:
    """Use the LLM to auto-answer every pending decision based on the requirement."""
    from pydantic import ValidationError

    from harness.llm import LLMOutputError, extract_json_block, load_prompt
    from harness.services.memory_service import inject_project_memory

    project_memory = inject_project_memory(db)
    template = load_prompt("decision_answerer")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user_template = parts[1].strip()

    answered = []
    for dec in decisions:
        if dec["status"] != DecisionStatus.PENDING:
            answered.append(dec)
            continue

        options: list[str] = json.loads(dec["options_json"]) if dec["options_json"] else []
        options_list = "\n".join(f"{i + 1}. {opt}" for i, opt in enumerate(options))
        recommendation = dec["recommendation"] or (options[0] if options else "No recommendation")

        user = (
            user_template
            .replace("{requirement}", task["raw_requirement"])
            .replace("{project_memory}", project_memory or "(none)")
            .replace("{category}", dec["category"])
            .replace("{question}", dec["question"])
            .replace("{options_list}", options_list)
            .replace("{recommendation}", recommendation)
        )

        selected = recommendation
        raw = ""
        try:
            raw = extract_json_block(llm.complete(system, user))
            parsed = _DecisionAnswer.model_validate_json(raw)
            selected = parsed.selected_answer
        except Exception:
            selected = recommendation

        # refresh task from DB before each answer call
        refreshed = db.get_active_task()
        if refreshed:
            task = dict(refreshed)
        answer_decision(dec["id"], selected, task, db)
        answered.append(dict(db.get_decision(dec["id"])))

    return answered
