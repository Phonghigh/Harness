import json

import typer
from pydantic import BaseModel, ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, extract_json_block, load_prompt, split_prompt
from harness.schemas.contract import ContractSpec, ContractStatus
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


class _ContractDraft(BaseModel):
    scope: str
    allowed_files: list[str]
    forbidden: list[str]
    spec: ContractSpec


def build_contract(task: dict, db: Database, llm: LLMAdapter | None = None) -> dict:
    assert_command_allowed("contract", TaskStatus(task["status"]))

    contract_id = db.new_contract_id()
    now = now_iso()

    if llm is not None:
        decisions = db.get_decisions(task["id"])
        decisions_text = "\n".join(
            f"- [{d['category']}] Q: {d['question']}\n  A: {d['selected_answer']}"
            for d in decisions
        )
        template = load_prompt("contract_builder")
        system, user_template = split_prompt(template)
        user = (
            user_template
            .replace("{task_title}", task["title"])
            .replace("{requirement}", task["raw_requirement"])
            .replace("{decisions}", decisions_text)
        )
        response = llm.complete(system, user)
        raw = extract_json_block(response.content)
        try:
            draft = _ContractDraft.model_validate_json(raw)
        except (ValidationError, ValueError) as e:
            raise RuntimeError(f"LLM returned invalid contract draft: {e}") from e

        contract = {
            "id": contract_id,
            "task_id": task["id"],
            "scope": draft.scope,
            "allowed_files_json": json.dumps(draft.allowed_files),
            "forbidden_json": json.dumps(draft.forbidden),
            "spec_json": draft.spec.model_dump_json(),
            "status": ContractStatus.APPROVED,
            "created_at": now,
        }
    else:
        stub_spec = ContractSpec(
            summary=f"[STUB] Implementation contract for: {task['title']}",
            files=[{"path": "src/main.py", "action": "create", "description": "Main implementation"}],
            constraints=["no new dependencies", "follow existing code style"],
            acceptance_criteria=["task completes without error"],
        )
        contract = {
            "id": contract_id,
            "task_id": task["id"],
            "scope": f"[STUB] {task['title']}",
            "allowed_files_json": json.dumps(["src/main.py"]),
            "forbidden_json": json.dumps(["TODO", "FIXME", "HACK"]),
            "spec_json": stub_spec.model_dump_json(),
            "status": ContractStatus.APPROVED,
            "created_at": now,
        }

    db.create_contract(contract)
    transition(task, TaskStatus.CONTRACT_READY, db)
    return contract
