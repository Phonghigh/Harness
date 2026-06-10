import json

from harness.db import Database, now_iso
from harness.schemas.contract import ContractStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition

_DEFAULT_FORBIDDEN = ["TODO", "FIXME", "HACK", "print(", "console.log(", "debugger"]


def build_contract(task: dict, db: Database, llm=None) -> dict:
    assert_command_allowed("contract", TaskStatus(task["status"]))

    if llm is not None:
        return _build_contract_llm(task, db, llm)
    return _build_contract_stub(task, db)


def _build_contract_llm(task: dict, db: Database, llm) -> dict:
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

    template = load_prompt("contract_builder")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{requirement}", task["raw_requirement"])
    user = user.replace("{decisions_json}", json.dumps(decisions_data, indent=2))

    raw_response = llm.complete(system, user)
    raw = extract_json_block(raw_response)

    try:
        spec = ContractSpec.model_validate_json(raw)
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
        "status": ContractStatus.APPROVED,
        "created_at": now_iso(),
    }
    db.create_contract(contract)
    transition(task, TaskStatus.CONTRACT_READY, db)
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
    contract = {
        "id": contract_id,
        "task_id": task["id"],
        "scope": f"[STUB] {task['title']}",
        "allowed_files_json": json.dumps(["src/main.py"]),
        "forbidden_json": json.dumps(_DEFAULT_FORBIDDEN),
        "spec_json": json.dumps(stub_spec),
        "status": ContractStatus.APPROVED,
        "created_at": now_iso(),
    }
    db.create_contract(contract)
    transition(task, TaskStatus.CONTRACT_READY, db)
    return contract
