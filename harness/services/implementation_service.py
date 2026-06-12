import json
from pathlib import Path

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


def implement(
    task: dict,
    contract: dict,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
) -> dict:
    assert_command_allowed("implement", TaskStatus(task["status"]))

    project_root = harness_dir.parent
    allowed_files = json.loads(contract["allowed_files_json"])

    file_parts = []
    for file_path in allowed_files:
        full_path = project_root / file_path
        if full_path.exists():
            content = full_path.read_text()
            file_parts.append(f"=== {file_path} ===\n{content}")
        else:
            file_parts.append(f"=== {file_path} ===\n(FILE DOES NOT EXIST YET)")
    file_contents = "\n\n".join(file_parts)

    contract_data = {
        "id": contract["id"],
        "scope": contract["scope"],
        "allowed_files": allowed_files,
        "forbidden": json.loads(contract["forbidden_json"]),
        "spec": json.loads(contract["spec_json"]),
    }

    template = load_prompt("syntax_executor")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{contract_json}", json.dumps(contract_data, indent=2))
    user = user.replace("{file_contents}", file_contents)

    raw_response = llm.complete(system, user)

    if raw_response.strip().startswith("SYNTAX_EXECUTOR_ERROR:"):
        raise LLMOutputError(raw_response.strip())

    diff_text = extract_json_block(raw_response) if "```" in raw_response else raw_response.strip()

    patches_dir = harness_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    patch_file = patches_dir / f"{contract['id']}.diff"
    patch_file.write_text(diff_text)

    patch_id = db.new_patch_id()
    db.create_patch({
        "id": patch_id,
        "contract_id": contract["id"],
        "diff_text": diff_text,
        "status": "generated",
        "created_at": now_iso(),
    })

    transition(task, TaskStatus.WAITING_FOR_PATCH_APPROVAL, db)

    return {
        "patch_id": patch_id,
        "patch_file": str(patch_file),
        "lines": diff_text.count("\n"),
    }


def approve_patch(task: dict, db: Database) -> None:
    """Human approves the patch. Task → IMPLEMENTING for compliance check."""
    assert_command_allowed("patch_approve", TaskStatus(task["status"]))
    transition(task, TaskStatus.IMPLEMENTING, db)


def reject_patch(task: dict, contract_id: str, db: Database) -> None:
    """Human rejects the patch. Task → CONTRACT_READY to re-implement."""
    assert_command_allowed("patch_reject", TaskStatus(task["status"]))
    patch = db.get_latest_patch(contract_id)
    if patch:
        db.update_patch_status(patch["id"], "rejected")
    transition(task, TaskStatus.CONTRACT_READY, db)


def reimplement(
    task: dict,
    contract: dict,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
    compliance_summary: str = "",
) -> dict:
    """Re-generate a patch for a task already in IMPLEMENTING state after compliance failure.

    Unlike implement(), this asserts IMPLEMENTING state and does not transition into it.
    """
    assert_command_allowed("reimplement", TaskStatus(task["status"]))

    project_root = harness_dir.parent
    allowed_files = json.loads(contract["allowed_files_json"])

    file_parts = []
    for file_path in allowed_files:
        full_path = project_root / file_path
        if full_path.exists():
            content = full_path.read_text()
            file_parts.append(f"=== {file_path} ===\n{content}")
        else:
            file_parts.append(f"=== {file_path} ===\n(FILE DOES NOT EXIST YET)")
    file_contents = "\n\n".join(file_parts)

    contract_data = {
        "id": contract["id"],
        "scope": contract["scope"],
        "allowed_files": allowed_files,
        "forbidden": json.loads(contract["forbidden_json"]),
        "spec": json.loads(contract["spec_json"]),
    }
    if compliance_summary:
        contract_data["compliance_feedback"] = compliance_summary

    template = load_prompt("syntax_executor")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{contract_json}", json.dumps(contract_data, indent=2))
    user = user.replace("{file_contents}", file_contents)

    raw_response = llm.complete(system, user)

    if raw_response.strip().startswith("SYNTAX_EXECUTOR_ERROR:"):
        raise LLMOutputError(raw_response.strip())

    diff_text = extract_json_block(raw_response) if "```" in raw_response else raw_response.strip()

    patches_dir = harness_dir / "patches"
    patches_dir.mkdir(exist_ok=True)
    patch_file = patches_dir / f"{contract['id']}.diff"
    patch_file.write_text(diff_text)

    patch_id = db.new_patch_id()
    db.create_patch({
        "id": patch_id,
        "contract_id": contract["id"],
        "diff_text": diff_text,
        "status": "generated",
        "created_at": now_iso(),
    })

    return {
        "patch_id": patch_id,
        "patch_file": str(patch_file),
        "lines": diff_text.count("\n"),
    }
