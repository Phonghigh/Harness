import json
from pathlib import Path

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt
from harness.schemas.task import TaskStatus
from harness.services.claude_executor import (
    build_impl_prompt,
    capture_diff_staged,
    is_claude_available,
    reset_allowed_files,
    run_claude_implement,
)
from harness.state_machine import assert_command_allowed, transition


def _prepare_impl_context(contract: dict, project_root: Path) -> tuple[str, dict]:
    """Build file_contents string and contract_data dict for the syntax executor prompt.

    Fixes modify→create for files that don't exist yet, preventing SYNTAX_EXECUTOR_ERROR.
    """
    allowed_files = json.loads(contract["allowed_files_json"])
    spec = json.loads(contract["spec_json"])

    # Build a set of files that don't exist so we can fix the spec
    missing: set[str] = {
        fp for fp in allowed_files
        if not (project_root / fp).exists()
    }

    # Patch spec: modify → create for non-existent files
    patched_files = []
    for f in spec.get("files", []):
        if f.get("action") == "modify" and f.get("path") in missing:
            f = {**f, "action": "create"}
        patched_files.append(f)
    patched_spec = {**spec, "files": patched_files}

    # Read file contents
    file_parts = []
    for file_path in allowed_files:
        full_path = project_root / file_path
        if full_path.exists():
            file_parts.append(f"=== {file_path} ===\n{full_path.read_text()}")
        else:
            file_parts.append(f"=== {file_path} ===\n(FILE DOES NOT EXIST YET — use create action)")
    file_contents = "\n\n".join(file_parts)

    contract_data = {
        "id": contract["id"],
        "scope": contract["scope"],
        "allowed_files": allowed_files,
        "forbidden": json.loads(contract["forbidden_json"]),
        "spec": patched_spec,
    }
    return file_contents, contract_data


def _call_syntax_executor(contract_data: dict, file_contents: str, llm: LLMAdapter) -> str:
    template = load_prompt("syntax_executor")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{contract_json}", json.dumps(contract_data, indent=2))
    user = user.replace("{file_contents}", file_contents)

    raw_response = llm.complete(system, user)

    if raw_response.strip().startswith("SYNTAX_EXECUTOR_ERROR:"):
        raise LLMOutputError(raw_response.strip())

    return extract_json_block(raw_response) if "```" in raw_response else raw_response.strip()


def implement(
    task: dict,
    contract: dict,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
    config=None,
) -> dict:
    assert_command_allowed("implement", TaskStatus(task["status"]))
    project_root = harness_dir.parent

    use_cc = (
        config is not None
        and getattr(config, "use_claude_code", False)
        and is_claude_available()
    )

    if use_cc:
        allowed_files = json.loads(contract["allowed_files_json"])
        contract_data = {
            "id": contract["id"],
            "scope": contract["scope"],
            "allowed_files": allowed_files,
            "forbidden": json.loads(contract["forbidden_json"]),
            "spec": json.loads(contract["spec_json"]),
        }
        prompt = build_impl_prompt(contract_data)
        timeout = getattr(config, "claude_code_timeout", 300)

        success, output = run_claude_implement(prompt, project_root, timeout)
        if not success:
            raise LLMOutputError(f"Claude Code failed:\n{output[:2000]}")

        diff_text = capture_diff_staged(project_root, allowed_files)
        if not diff_text.strip():
            raise LLMOutputError(
                "Claude Code ran successfully but produced no file changes. "
                f"Claude output:\n{output[:1000]}"
            )
    else:
        file_contents, contract_data = _prepare_impl_context(contract, project_root)
        diff_text = _call_syntax_executor(contract_data, file_contents, llm)

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
        "mode": "claude_code" if use_cc else "llm",
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
    config=None,
) -> dict:
    """Re-generate patch when already in IMPLEMENTING state (compliance retry)."""
    assert_command_allowed("reimplement", TaskStatus(task["status"]))
    project_root = harness_dir.parent

    use_cc = (
        config is not None
        and getattr(config, "use_claude_code", False)
        and is_claude_available()
    )

    if use_cc:
        allowed_files = json.loads(contract["allowed_files_json"])
        contract_data = {
            "id": contract["id"],
            "scope": contract["scope"],
            "allowed_files": allowed_files,
            "forbidden": json.loads(contract["forbidden_json"]),
            "spec": json.loads(contract["spec_json"]),
        }

        reset_allowed_files(project_root, allowed_files)

        prompt = build_impl_prompt(contract_data, compliance_feedback=compliance_summary)
        timeout = getattr(config, "claude_code_timeout", 300)

        success, output = run_claude_implement(prompt, project_root, timeout)
        if not success:
            raise LLMOutputError(f"Claude Code failed on reimplement:\n{output[:2000]}")

        diff_text = capture_diff_staged(project_root, allowed_files)
        if not diff_text.strip():
            raise LLMOutputError("Claude Code produced no changes on reimplement")
    else:
        file_contents, contract_data = _prepare_impl_context(contract, project_root)
        if compliance_summary:
            contract_data["compliance_feedback"] = compliance_summary
        diff_text = _call_syntax_executor(contract_data, file_contents, llm)

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
        "mode": "claude_code" if use_cc else "llm",
    }
