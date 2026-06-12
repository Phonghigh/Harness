import json

from harness.db import Database, now_iso
from harness.schemas.contract import ContractStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition

_DEFAULT_FORBIDDEN = ["TODO", "FIXME", "HACK", "print(", "console.log(", "debugger"]


def build_contract(task: dict, db: Database, llm=None, harness_dir=None, config=None) -> dict:
    assert_command_allowed("contract", TaskStatus(task["status"]))

    if llm is not None:
        return _build_contract_llm(task, db, llm, harness_dir=harness_dir, config=config)
    return _build_contract_stub(task, db)


def _build_contract_llm(task: dict, db: Database, llm, harness_dir=None, config=None) -> dict:
    from pydantic import ValidationError

    from harness.llm import LLMOutputError, extract_json_block, load_prompt
    from harness.schemas.contract import ContractSpec

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
    decision_ids = [d["id"] for d in decisions]

    from pathlib import Path
    from harness.services.scanner_service import build_file_tree
    max_depth = config.context_max_depth if config else 4
    harness_path = Path(harness_dir) if harness_dir else None
    file_tree = build_file_tree(harness_path.parent, max_depth=max_depth) if harness_path else "(unknown)"

    template = load_prompt("contract_builder")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{requirement}", task["raw_requirement"])
    user = user.replace("{decisions_json}", json.dumps(decisions_data, indent=2))
    user = user.replace("{file_tree}", file_tree)

    raw_response = llm.complete(system, user)
    raw = extract_json_block(raw_response)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"LLM returned non-JSON response: {e}") from e

    if "error" in parsed and len(parsed) == 1:
        raise LLMOutputError(f"Contract builder refused: {parsed['error']}")

    try:
        spec = ContractSpec.model_validate(parsed)
    except ValidationError as e:
        raise LLMOutputError(f"LLM returned invalid ContractSpec: {e}") from e

    allowed_files = [f.path for f in spec.files]
    contract_id = db.new_contract_id()
    contract = {
        "id": contract_id,
        "task_id": task["id"],
        "scope": spec.summary,
        "allowed_files_json": json.dumps(allowed_files),
        "forbidden_json": json.dumps(_DEFAULT_FORBIDDEN),
        "spec_json": spec.model_dump_json(),
        "status": ContractStatus.DRAFT,
        "decision_ids_json": json.dumps(decision_ids),
        "created_at": now_iso(),
    }
    db.create_contract(contract)
    transition(task, TaskStatus.WAITING_FOR_CONTRACT_APPROVAL, db)
    return contract


def _build_contract_stub(task: dict, db: Database) -> dict:
    contract_id = db.new_contract_id()
    stub_spec = {
        "summary": f"[STUB] Implementation contract for: {task['title']}",
        "files": [
            {"path": "src/main.py", "action": "create", "description": "Main implementation"},
        ],
        "constraints": ["no new dependencies", "follow existing code style"],
        "acceptance_criteria": ["task completes without error"],
    }
    decision_ids = [d["id"] for d in db.get_decisions(task["id"])]
    contract = {
        "id": contract_id,
        "task_id": task["id"],
        "scope": f"[STUB] {task['title']}",
        "allowed_files_json": json.dumps(["src/main.py"]),
        "forbidden_json": json.dumps(_DEFAULT_FORBIDDEN),
        "spec_json": json.dumps(stub_spec),
        "status": ContractStatus.DRAFT,
        "decision_ids_json": json.dumps(decision_ids),
        "created_at": now_iso(),
    }
    db.create_contract(contract)
    transition(task, TaskStatus.WAITING_FOR_CONTRACT_APPROVAL, db)
    return contract


def approve_contract(task: dict, contract_id: str, db: Database) -> None:
    """Human approves the contract. Task → CONTRACT_READY."""
    assert_command_allowed("contract_approve", TaskStatus(task["status"]))
    db.update_contract_status(contract_id, ContractStatus.APPROVED)
    transition(task, TaskStatus.CONTRACT_READY, db)


def reject_contract(task: dict, db: Database) -> None:
    """Human rejects the contract. Task → DECISIONS_APPROVED to rebuild."""
    assert_command_allowed("contract_reject", TaskStatus(task["status"]))
    transition(task, TaskStatus.DECISIONS_APPROVED, db)
