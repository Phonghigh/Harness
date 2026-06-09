import json

from harness.db import Database, now_iso
from harness.schemas.contract import ContractStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


def build_contract(task: dict, db: Database) -> dict:
    assert_command_allowed("contract", TaskStatus(task["status"]))

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
        "forbidden_json": json.dumps(["TODO", "FIXME", "HACK"]),
        "spec_json": json.dumps(stub_spec),
        "status": ContractStatus.APPROVED,
        "created_at": now_iso(),
    }
    db.create_contract(contract)
    transition(task, TaskStatus.CONTRACT_READY, db)
    return contract
