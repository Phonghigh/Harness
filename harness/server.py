"""
Harness MCP server — exposes the decision-first coding control plane as MCP tools and resources.

This is a transport adapter only. All business logic lives in harness/services/.
Same dependency level as cli.py: imports services, not the other way around.

Usage with Claude Code:
  Add to .claude/mcp.json:
  { "harness": { "command": "harness", "args": ["serve"], "type": "stdio" } }
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from harness.config import HarnessConfig, load_config
from harness.db import Database, now_iso
from harness.llm import LLMAdapter, build_adapter
from harness.schemas.task import TaskStatus
from harness.services.contract_service import build_contract
from harness.services.decision_service import (
    answer_decision,
    approve_decisions,
    generate_stub_decisions,
    list_decisions,
)
from harness.services.implementation_service import implement as run_implement
from harness.services.memory_service import write_memory
from harness.services.task_service import create_task, run_interrogate
from harness.services.validation_service import check_compliance
from harness.state_machine import transition

mcp = FastMCP(
    "harness",
    instructions=(
        "Harness is a decision-first AI coding control plane. "
        "The human owns all architecture decisions — AI executes syntax only. "
        "Workflow: create_task → interrogate → answer + approve decisions → build_contract "
        "→ implement → check_compliance → validate → write_memory. "
        "NEVER apply patches automatically. Patch application is always manual."
    ),
)

# Lazy singletons — loaded on first tool call
_harness_dir: Path | None = None
_config: HarnessConfig | None = None
_db: Database | None = None


def _ctx() -> tuple[Path, HarnessConfig, Database]:
    global _harness_dir, _config, _db
    if _db is None:
        _harness_dir, _config = load_config()
        _db = Database(_harness_dir / "harness.db")
    return _harness_dir, _config, _db


def _get_llm() -> LLMAdapter | None:
    from harness.config import EnvSettings
    _, config, _ = _ctx()
    env = EnvSettings()
    provider = env.harness_provider or config.llm_provider
    has_key = (
        (provider == "anthropic" and env.anthropic_api_key)
        or (provider == "openai" and env.openai_api_key)
    )
    if not has_key:
        return None
    return build_adapter(config.llm_provider, config.llm_model)


def _active_task() -> dict | None:
    _, _, db = _ctx()
    row = db.get_active_task()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def harness_create_task(requirement: str) -> dict:
    """Create a new task from a requirement string. One active task at a time."""
    _, _, db = _ctx()
    task = create_task(requirement, db)
    return {"task_id": task["id"], "title": task["title"], "status": task["status"]}


@mcp.tool()
def harness_interrogate() -> dict:
    """
    Run LLM interrogation to extract 5–10 architectural decisions for the active task.
    Uses project memory to avoid re-asking already-decided patterns.
    """
    _, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task. Use harness_create_task() first."}
    llm = _get_llm()
    decisions = run_interrogate(task, llm, db) if llm else generate_stub_decisions(task, db)
    return {
        "decisions_generated": len(decisions),
        "decisions": [
            {
                "id": d["id"],
                "category": d["category"],
                "question": d["question"],
                "options": json.loads(d["options_json"]) if isinstance(d.get("options_json"), str) else d.get("options", []),
                "recommendation": d.get("recommendation"),
            }
            for d in decisions
        ],
    }


@mcp.tool()
def harness_list_decisions() -> dict:
    """List all decisions for the active task with status and answers."""
    _, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    rows = list_decisions(task["id"], db)
    return {
        "task_id": task["id"],
        "decisions": [
            {
                "id": d["id"],
                "category": d["category"],
                "status": d["status"],
                "question": d["question"],
                "recommendation": d["recommendation"],
                "selected_answer": d["selected_answer"],
            }
            for d in rows
        ],
    }


@mcp.tool()
def harness_answer_decision(decision_id: str, answer: str) -> dict:
    """
    Record a human answer for a specific decision.
    IMPORTANT: The human must provide the answer. AI must not choose architecture for the human.
    """
    _, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    answer_decision(decision_id, answer, task, db)
    return {"decision_id": decision_id.upper(), "answer": answer, "status": "answered"}


@mcp.tool()
def harness_approve_decisions(decision_ids: list[str]) -> dict:
    """
    Approve answered decisions. Checks for conflicts with project memory.
    When all decisions are approved, task transitions to DECISIONS_APPROVED.
    """
    _, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    llm = _get_llm()
    all_approved, conflicts = approve_decisions(decision_ids, task, db, llm)
    return {
        "all_decisions_approved": all_approved,
        "approved_ids": [d.upper() for d in decision_ids],
        "conflicts": [c.get("warning", "") for c in conflicts],
        "next_step": "harness_build_contract()" if all_approved else "Answer and approve remaining decisions",
    }


@mcp.tool()
def harness_build_contract() -> dict:
    """Build an implementation contract from all approved decisions via LLM."""
    _, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    llm = _get_llm()
    c = build_contract(task, db, llm)
    return {
        "contract_id": c["id"],
        "scope": c["scope"],
        "allowed_files": json.loads(c["allowed_files_json"]),
        "forbidden_patterns": json.loads(c["forbidden_json"]),
        "decision_ids": json.loads(c.get("decision_ids_json", "[]")),
        "next_step": f"harness_implement('{c['id']}')",
    }


@mcp.tool()
def harness_implement(contract_id: str) -> dict:
    """
    Generate a unified diff patch from the contract via LLM.
    Patch saved to .harness/patches/<contract_id>.diff.
    NEVER apply the patch automatically — patch application is always a manual human step.
    """
    harness_dir, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    llm = _get_llm()
    if llm is None:
        return {"error": "API key required for patch generation."}
    c = db.get_contract(contract_id.upper())
    if c is None:
        return {"error": f"Contract {contract_id} not found."}
    result = run_implement(task, dict(c), harness_dir, llm, db)
    # Load diff preview from DB
    patch = db.get_patch(result["patch_id"])
    diff_text = patch["diff_text"] if patch else ""
    lines = diff_text.split("\n")
    preview_lines = lines[:80]
    preview = "\n".join(preview_lines)
    if len(lines) > 80:
        preview += f"\n... ({len(lines) - 80} more lines)"
    return {
        "patch_id": result["patch_id"],
        "patch_file": result["patch_file"],
        "total_lines": result["lines"],
        "diff_preview": preview,
        "next_step": (
            f"Review the patch at {result['patch_file']}, "
            f"then: harness_check_compliance('{contract_id}')"
        ),
    }


@mcp.tool()
def harness_check_compliance(contract_id: str) -> dict:
    """Run two-phase compliance check: rule-based + LLM semantic review against the contract."""
    harness_dir, _, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    llm = _get_llm()
    if llm is None:
        return {"error": "API key required for LLM compliance check."}
    c = db.get_contract(contract_id.upper())
    if c is None:
        return {"error": f"Contract {contract_id} not found."}
    patch = db.get_latest_patch(contract_id.upper())
    if patch is None:
        return {"error": f"No patch for {contract_id}. Run harness_implement first."}
    report = check_compliance(task, dict(c), patch["diff_text"], harness_dir, llm, db)
    return {
        "passed": report.passed,
        "rule_based_passed": report.rule_based_passed,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
        "violations": [v.model_dump() for v in report.violations],
        "summary": report.summary,
        "llm_review": report.llm_review,
        "next_step": (
            f"Apply patch manually:\n  git apply .harness/patches/{contract_id.upper()}.diff\n"
            "Then: harness_validate()"
            if report.passed
            else "Compliance FAILED. Fix and re-run harness_implement()."
        ),
    }


@mcp.tool()
def harness_validate() -> dict:
    """Run configured validation commands (build/test/lint). Empty config = auto-pass."""
    _, config, db = _ctx()
    task = _active_task()
    if task is None:
        return {"error": "No active task."}
    from harness.state_machine import assert_command_allowed
    assert_command_allowed("validate", TaskStatus(task["status"]))

    if not config.validate_commands:
        validating = {"id": task["id"], "status": TaskStatus.VALIDATING}
        transition(validating, TaskStatus.DONE, db)
        return {"passed": True, "commands": [], "message": "No validate_commands — auto-PASS. Task → DONE"}

    results = []
    all_passed = True
    for cmd in config.validate_commands:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        ok = proc.returncode == 0
        if not ok:
            all_passed = False
        results.append({"command": cmd, "passed": ok, "returncode": proc.returncode})

    validating = {"id": task["id"], "status": TaskStatus.VALIDATING}
    if all_passed:
        transition(validating, TaskStatus.DONE, db)
    else:
        transition(validating, TaskStatus.IMPLEMENTING, db)

    return {
        "passed": all_passed,
        "commands": results,
        "next_step": "harness_write_memory()" if all_passed else "Fix failures and re-implement.",
    }


@mcp.tool()
def harness_write_memory() -> dict:
    """Extract 2–6 reusable architectural lessons from the completed task into project memory."""
    _, config, db = _ctx()
    task = db.get_latest_task()
    if task is None:
        return {"error": "No task found."}
    task = dict(task)
    llm = _get_llm()
    if llm is None:
        return {"error": "API key required for memory extraction."}
    saved = write_memory(task, llm, db, config)
    return {
        "saved_count": len(saved),
        "memories": [
            {
                "type": m["type"],
                "key": m["key"],
                "lesson": json.loads(m["value_json"]).get("lesson", ""),
            }
            for m in saved
        ],
    }


@mcp.tool()
def harness_get_status() -> dict:
    """Get current task status, decision coverage percentage, and next recommended action."""
    _, _, db = _ctx()
    task = db.get_active_task()
    if task is None:
        return {"active_task": None, "message": "No active task. Use harness_create_task() to start."}
    task = dict(task)
    decisions = db.get_decisions(task["id"])
    total = len(decisions)
    answered = sum(1 for d in decisions if d["status"] in ("answered", "approved"))
    approved = sum(1 for d in decisions if d["status"] == "approved")

    next_steps = {
        "INTAKE": "harness_interrogate()",
        "INTERROGATING": "Wait for interrogation to complete",
        "WAITING_FOR_DECISIONS": "harness_list_decisions() → harness_answer_decision() → harness_approve_decisions()",
        "DECISIONS_APPROVED": "harness_build_contract()",
        "CONTRACT_READY": "harness_implement('<contract_id>')",
        "IMPLEMENTING": "harness_check_compliance('<contract_id>')",
        "CHECKING_COMPLIANCE": "Wait for compliance check",
        "VALIDATING": "harness_validate()",
        "DONE": "harness_write_memory()",
    }

    return {
        "task_id": task["id"],
        "title": task["title"],
        "status": task["status"],
        "decision_coverage": {
            "total": total,
            "answered": answered,
            "approved": approved,
            "coverage_pct": round(answered / total * 100) if total else 0,
        },
        "next_step": next_steps.get(task["status"], "Unknown state"),
    }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("harness://active_task")
def resource_active_task() -> str:
    """Current active task with status and decision coverage summary."""
    _, _, db = _ctx()
    task = db.get_active_task()
    if task is None:
        return json.dumps({"error": "No active task"})
    task = dict(task)
    decisions = db.get_decisions(task["id"])
    total = len(decisions)
    answered = sum(1 for d in decisions if d["status"] in ("answered", "approved"))
    return json.dumps({
        "id": task["id"],
        "title": task["title"],
        "status": task["status"],
        "requirement": task["raw_requirement"],
        "decisions_total": total,
        "decisions_answered": answered,
        "created_at": task["created_at"],
    }, indent=2)


@mcp.resource("harness://decisions/{task_id}")
def resource_decisions(task_id: str) -> str:
    """All decisions for a task with current status and answers."""
    _, _, db = _ctx()
    rows = db.get_decisions(task_id)
    return json.dumps([
        {
            "id": d["id"],
            "category": d["category"],
            "status": d["status"],
            "question": d["question"],
            "options": json.loads(d["options_json"]),
            "recommendation": d["recommendation"],
            "selected_answer": d["selected_answer"],
        }
        for d in rows
    ], indent=2)


@mcp.resource("harness://contract/{task_id}")
def resource_contract(task_id: str) -> str:
    """Latest implementation contract for a task."""
    _, _, db = _ctx()
    contract = db.get_latest_contract(task_id)
    if contract is None:
        return json.dumps({"error": f"No contract for task {task_id}"})
    return json.dumps({
        "id": contract["id"],
        "scope": contract["scope"],
        "allowed_files": json.loads(contract["allowed_files_json"]),
        "forbidden": json.loads(contract["forbidden_json"]),
        "decision_ids": json.loads(contract["decision_ids_json"]),
        "spec": json.loads(contract["spec_json"]),
        "status": contract["status"],
    }, indent=2)


@mcp.resource("harness://memories")
def resource_memories() -> str:
    """All project memories with usage tracking."""
    _, _, db = _ctx()
    rows = db.list_memory()
    return json.dumps([
        {
            "id": m["id"],
            "type": m["type"],
            "scope": m["scope"],
            "key": m["key"],
            "value": json.loads(m["value_json"]),
            "applied_count": m["applied_count"],
            "last_applied_at": m["last_applied_at"],
        }
        for m in rows
    ], indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
