import json
import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.table import Table

from harness.config import HarnessConfig, load_config, save_config
from harness.db import Database, now_iso
from harness.schemas.task import TaskStatus
from harness.services.contract_service import build_contract
from harness.services.decision_service import (
    answer_decision,
    approve_decisions,
    generate_stub_decisions,
    list_decisions,
)
from harness.services.implementation_service import implement as run_implement
from harness.services.task_service import create_task, run_interrogate
from harness.services.validation_service import check_compliance
from harness.state_machine import (
    WrongStateError,
    assert_command_allowed,
    transition,
)

app = typer.Typer(no_args_is_help=True, help="Architect-Driven Coding Harness")
memory_app = typer.Typer(no_args_is_help=True, help="Memory commands")
config_app = typer.Typer(no_args_is_help=True, help="Config commands")
app.add_typer(memory_app, name="memory")
app.add_typer(config_app, name="config")


def _get_ctx() -> tuple[Path, HarnessConfig, Database]:
    try:
        harness_dir, config = load_config()
    except ValueError as e:
        _abort(str(e))
    db = Database(harness_dir / "harness.db")
    return harness_dir, config, db


def _abort(msg: str) -> None:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)


def _get_active_task_or_exit(db: Database) -> dict:
    task = db.get_active_task()
    if task is None:
        _abort("No active task. Run 'harness start \"requirement\"' first.")
    return dict(task)


def _get_llm(config: HarnessConfig):
    """Return an LLMAdapter if an API key is available, else None."""
    from harness.config import EnvSettings
    from harness.llm import build_adapter
    env = EnvSettings()
    provider = env.harness_provider or config.llm_provider
    has_key = (
        (provider == "anthropic" and env.anthropic_api_key)
        or (provider == "openai" and env.openai_api_key)
    )
    if not has_key:
        return None
    return build_adapter(
        config.llm_provider, config.llm_model,
        max_tokens=config.max_tokens, retries=config.llm_retries,
    )


# ---------------------------------------------------------------------------
# harness init
# ---------------------------------------------------------------------------

@app.command()
def init(
    provider: Annotated[str, typer.Option("--provider", help="LLM provider: anthropic or openai")],
    model: Annotated[str, typer.Option("--model", help="LLM model ID")],
) -> None:
    """Initialise a new harness project in the current directory."""
    harness_dir = Path.cwd() / ".harness"
    if harness_dir.exists():
        _abort(".harness/ already exists. Project already initialised.")

    harness_dir.mkdir()
    (harness_dir / "patches").mkdir()

    config = HarnessConfig(
        project_name=Path.cwd().name,
        llm_provider=provider,
        llm_model=model,
    )
    save_config(harness_dir, config)

    db = Database(harness_dir / "harness.db")
    db.initialize()

    typer.echo(f"Initialised harness project in {harness_dir}")
    typer.echo(f"Provider: {provider}  Model: {model}")
    typer.echo("Next: harness start \"your requirement\"")


# ---------------------------------------------------------------------------
# harness start
# ---------------------------------------------------------------------------

@app.command()
def start(requirement: str) -> None:
    """Create a new task from a requirement string."""
    _, _, db = _get_ctx()
    try:
        task = create_task(requirement, db)
    except ValueError as e:
        _abort(str(e))
    typer.echo(f"Task {task['id']} created.")
    typer.echo(f"Title: {task['title']}")
    typer.echo(f"Status: {task['status']}")
    typer.echo("\nNext: harness interrogate")


# ---------------------------------------------------------------------------
# harness status
# ---------------------------------------------------------------------------

@app.command()
def status() -> None:
    """Show current task state and decision coverage."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)

    typer.echo(f"Task {task['id']}: {task['title']} [{task['status']}]")

    decisions = db.get_decisions(task["id"])
    if decisions:
        total = len(decisions)
        answered = sum(1 for d in decisions if d["status"] in ("answered", "approved"))
        approved = sum(1 for d in decisions if d["status"] == "approved")
        coverage_pct = int(answered / total * 100) if total else 0
        approved_pct = int(approved / total * 100) if total else 0
        typer.echo(
            f"\nDecisions: {total} total | "
            f"Coverage: {answered}/{total} answered ({coverage_pct}%) | "
            f"Approved: {approved}/{total} ({approved_pct}%)"
        )
        for d in decisions:
            mark = {"pending": "✗", "answered": "△", "approved": "✓"}.get(d["status"], "?")
            typer.echo(f"  {mark} {d['id']}  {d['category']:<25} ({d['status']})")
    else:
        typer.echo("No decisions yet.")

    status_val = TaskStatus(task["status"])
    next_steps = {
        TaskStatus.INTAKE: "Next: harness interrogate",
        TaskStatus.INTERROGATING: "Interrogating in progress...",
        TaskStatus.WAITING_FOR_DECISIONS: "Next: harness answer <D-ID> \"answer\" → harness approve <D-ID>",
        TaskStatus.DECISIONS_APPROVED: "Next: harness contract",
        TaskStatus.CONTRACT_READY: "Next: harness implement <C-ID>",
        TaskStatus.IMPLEMENTING: "Next: harness check <C-ID>",
        TaskStatus.CHECKING_COMPLIANCE: "Compliance check in progress...",
        TaskStatus.VALIDATING: "Next: harness validate",
        TaskStatus.DONE: "Task is DONE. Next: harness remember",
    }
    typer.echo(f"\n{next_steps.get(status_val, '')}")


# ---------------------------------------------------------------------------
# harness interrogate
# ---------------------------------------------------------------------------

@app.command()
def interrogate() -> None:
    """Generate decision map for the active task via LLM (or stub if no API key)."""
    harness_dir, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("interrogate", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    llm = _get_llm(config)
    if llm is not None:
        typer.echo("Interrogating requirement via LLM...")
        try:
            decisions = run_interrogate(task, llm, db, harness_dir=harness_dir, config=config)
        except Exception as e:
            _abort(f"LLM interrogation failed: {e}")
    else:
        typer.echo("[STUB] No API key found — using stub decisions.")
        decisions = generate_stub_decisions(task, db)

    typer.echo(f"\nDecision Map ({len(decisions)} decisions generated):\n")
    typer.echo(f"{'ID':<6} {'Category':<25} {'Status':<10} Question")
    typer.echo("-" * 80)
    for d in decisions:
        typer.echo(f"{d['id']:<6} {d['category']:<25} {d['status']:<10} {d['question']}")

    typer.echo("\nNext: harness decisions → harness answer D001 \"...\"")


# ---------------------------------------------------------------------------
# harness decisions
# ---------------------------------------------------------------------------

@app.command()
def decisions() -> None:
    """List all decisions for the active task."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    rows = list_decisions(task["id"], db)

    if not rows:
        typer.echo("No decisions yet. Run 'harness interrogate' first.")
        return

    table = Table(title=f"Decisions for {task['id']}")
    table.add_column("ID", style="cyan")
    table.add_column("Category")
    table.add_column("Status", style="bold")
    table.add_column("Question")
    table.add_column("Answer")

    for d in rows:
        answer = d["selected_answer"] or ""
        status_color = {"pending": "red", "answered": "yellow", "approved": "green"}.get(
            d["status"], "white"
        )
        table.add_row(
            d["id"],
            d["category"],
            f"[{status_color}]{d['status']}[/{status_color}]",
            d["question"],
            answer[:40] + ("..." if len(answer) > 40 else ""),
        )
    rprint(table)


# ---------------------------------------------------------------------------
# harness answer
# ---------------------------------------------------------------------------

@app.command()
def answer(
    decision_id: Annotated[Optional[str], typer.Argument()] = None,
    answer_text: Annotated[Optional[str], typer.Argument()] = None,
) -> None:
    """Record an answer for a decision. Omit arguments to enter interactive mode."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("answer", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    if decision_id is None:
        pending = [d for d in db.get_decisions(task["id"]) if d["status"] == "pending"]
        if not pending:
            typer.echo("No pending decisions.")
            return
        typer.echo("Pending decisions:")
        for d in pending:
            typer.echo(f"  {d['id']}  {d['category']:<25}  {d['question']}")
        decision_id = typer.prompt("\nDecision ID to answer").strip().upper()

    dec = db.get_decision(decision_id.upper())
    if dec is None:
        _abort(f"Decision {decision_id} not found.")

    if answer_text is None:
        options = json.loads(dec["options_json"])
        typer.echo(f"\n{dec['question']}")
        if dec["recommendation"]:
            typer.echo(f"Recommendation: {dec['recommendation']}")
        typer.echo("\nOptions:")
        for i, opt in enumerate(options, 1):
            typer.echo(f"  {i}. {opt}")
        answer_text = typer.prompt("\nYour answer")

    answer_decision(decision_id, answer_text, task, db)
    typer.echo(f"Decision {decision_id.upper()} answered.")
    typer.echo(f"Next: harness approve {decision_id.upper()}")


# ---------------------------------------------------------------------------
# harness approve
# ---------------------------------------------------------------------------

@app.command()
def approve(
    decision_ids: Annotated[Optional[list[str]], typer.Argument()] = None,
    all_flag: Annotated[bool, typer.Option("--all", help="Approve all answered decisions")] = False,
) -> None:
    """Approve one or more answered decisions, or --all to approve every answered decision."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("approve", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    if all_flag:
        decision_ids = [
            d["id"] for d in db.get_decisions(task["id"]) if d["status"] == "answered"
        ]
        if not decision_ids:
            typer.echo("No answered decisions to approve.")
            return
    elif not decision_ids:
        _abort("Provide decision IDs or use --all.")

    try:
        all_approved, conflicts = approve_decisions(decision_ids, task, db)
    except ValueError as e:
        _abort(str(e))
    for did in decision_ids:
        typer.echo(f"Decision {did.upper()} approved.")

    if conflicts:
        typer.echo("\n[WARNING] Possible conflicts with project memory:")
        for c in conflicts:
            typer.echo(f"  ⚠  {c['warning']}")

    if all_approved:
        typer.echo("\nAll decisions approved! Task → DECISIONS_APPROVED")
        typer.echo("Next: harness contract")
    else:
        remaining = db.get_pending_decisions(task["id"])
        typer.echo(f"\n{len(remaining)} decision(s) still pending.")


# ---------------------------------------------------------------------------
# harness contract
# ---------------------------------------------------------------------------

@app.command()
def contract() -> None:
    """Build implementation contract from approved decisions via LLM."""
    harness_dir, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("contract", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    llm = _get_llm(config)
    if llm is not None:
        typer.echo("Building contract via LLM...")
    else:
        typer.echo("[STUB] No API key found — using stub contract.")
    try:
        c = build_contract(task, db, llm, harness_dir=harness_dir, config=config)
    except Exception as e:
        _abort(f"Contract build failed: {e}")
    allowed = json.loads(c["allowed_files_json"])
    forbidden = json.loads(c["forbidden_json"])

    typer.echo(f"\nContract {c['id']} created.")
    typer.echo(f"Scope: {c['scope']}")
    typer.echo(f"\nAllowed files ({len(allowed)}):")
    for f in allowed:
        typer.echo(f"  {f}")
    typer.echo(f"\nForbidden patterns: {', '.join(forbidden)}")
    typer.echo(f"\nNext: review the contract, then run:")
    typer.echo(f"  harness contract-approve   (approve and proceed to implementation)")
    typer.echo(f"  harness contract-reject    (reject and rebuild from decisions)")


# ---------------------------------------------------------------------------
# harness implement
# ---------------------------------------------------------------------------

@app.command()
def implement(contract_id: str) -> None:
    """Generate patch file from contract via LLM (or stub if no API key)."""
    harness_dir, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("implement", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    c = db.get_contract(contract_id.upper())
    if c is None:
        _abort(f"Contract {contract_id} not found.")

    llm = _get_llm(config)
    if llm is not None:
        typer.echo(f"Generating patch for {contract_id.upper()} via LLM...")
        try:
            result = run_implement(task, dict(c), harness_dir, llm, db)
            patch_file = result["patch_file"]
            lines = result["lines"]
        except Exception as e:
            _abort(f"Implementation failed: {e}")
    else:
        typer.echo(f"[STUB] No API key found — writing stub patch for {contract_id.upper()}.")
        allowed = json.loads(c["allowed_files_json"])
        stub_diff = _make_stub_diff(contract_id.upper(), allowed)
        patches_dir = harness_dir / "patches"
        patches_dir.mkdir(exist_ok=True)
        patch_file = str(patches_dir / f"{contract_id.upper()}.diff")
        Path(patch_file).write_text(stub_diff)
        patch_id = db.new_patch_id()
        db.create_patch({
            "id": patch_id,
            "contract_id": contract_id.upper(),
            "diff_text": stub_diff,
            "status": "generated",
            "created_at": now_iso(),
        })
        transition(task, TaskStatus.WAITING_FOR_PATCH_APPROVAL, db)
        lines = stub_diff.count("\n")

    typer.echo(f"Patch saved: {patch_file}")
    typer.echo(f"Lines: {lines}")
    typer.echo("")
    # Inline diff preview (first 40 added/removed lines)
    try:
        diff_content = Path(patch_file).read_text()
        diff_lines = diff_content.split("\n")
        shown = 0
        typer.echo("─" * 60)
        for line in diff_lines:
            if shown >= 40:
                remaining = len(diff_lines) - diff_lines.index(line)
                typer.echo(f"  ... ({remaining} more lines — see {patch_file})")
                break
            if line.startswith("+") and not line.startswith("+++"):
                typer.echo(typer.style(line, fg=typer.colors.GREEN))
                shown += 1
            elif line.startswith("-") and not line.startswith("---"):
                typer.echo(typer.style(line, fg=typer.colors.RED))
                shown += 1
            else:
                typer.echo(line)
        typer.echo("─" * 60)
    except Exception:
        pass
    typer.echo(f"\nNext: review the patch, then run:")
    typer.echo(f"  harness apply              (approve patch → run compliance check)")
    typer.echo(f"  harness patch-reject       (reject patch → re-implement)")


def _make_stub_diff(contract_id: str, allowed_files: list[str]) -> str:
    lines = []
    for path in allowed_files:
        lines += [
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -0,0 +1,3 @@",
            f"+# [STUB] Generated by harness implement",
            f"+# Contract: {contract_id}",
            f"+# Placeholder implementation",
        ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# harness contract-approve / contract-reject
# ---------------------------------------------------------------------------

@app.command("contract-approve")
def contract_approve() -> None:
    """Approve the pending contract and advance to implementation."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("contract_approve", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    from harness.services.contract_service import approve_contract
    c = db.get_latest_contract(task["id"])
    if c is None:
        _abort("No contract found.")
    approve_contract(task, c["id"], db)
    typer.echo(f"Contract {c['id']} approved. Task → CONTRACT_READY")
    typer.echo(f"Next: harness implement {c['id']}")


@app.command("contract-reject")
def contract_reject() -> None:
    """Reject the pending contract. Task returns to DECISIONS_APPROVED for rebuild."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("contract_reject", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    from harness.services.contract_service import reject_contract
    reject_contract(task, db)
    typer.echo("Contract rejected. Task → DECISIONS_APPROVED")
    typer.echo("Next: harness contract  (rebuild contract from decisions)")


# ---------------------------------------------------------------------------
# harness apply / harness patch-reject
# ---------------------------------------------------------------------------

@app.command()
def apply() -> None:
    """Approve the generated patch and advance to compliance checking."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("patch_approve", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    from harness.services.implementation_service import approve_patch
    c = db.get_latest_contract(task["id"])
    approve_patch(task, db)
    typer.echo("Patch approved. Task → IMPLEMENTING")
    if c:
        typer.echo(f"Next: harness check {c['id']}")


@app.command("patch-reject")
def patch_reject() -> None:
    """Reject the generated patch. Task returns to CONTRACT_READY for re-implementation."""
    _, _, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("patch_reject", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    from harness.services.implementation_service import reject_patch
    c = db.get_latest_contract(task["id"])
    if c is None:
        _abort("No contract found.")
    reject_patch(task, c["id"], db)
    typer.echo("Patch rejected. Task → CONTRACT_READY")
    typer.echo(f"Next: harness implement {c['id']}  (re-generate patch)")


# ---------------------------------------------------------------------------
# harness check
# ---------------------------------------------------------------------------

@app.command()
def check(contract_id: str) -> None:
    """Run compliance check on patch (rule-based + LLM semantic review)."""
    harness_dir, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("check", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    c = db.get_contract(contract_id.upper())
    if c is None:
        _abort(f"Contract {contract_id} not found.")

    patch = db.get_latest_patch(contract_id.upper())
    if patch is None:
        _abort(f"No patch found for {contract_id}. Run 'harness implement {contract_id}' first.")

    llm = _get_llm(config)
    if llm is not None:
        typer.echo("Running compliance check (rule-based + LLM)...")
        try:
            report = check_compliance(
                task, dict(c), patch["diff_text"], harness_dir, llm, db
            )
        except Exception as e:
            _abort(f"Compliance check failed: {e}")

        verdict = "PASS" if report.passed else "FAIL"
        rule_verdict = "PASS" if report.rule_based_passed else "FAIL"
        typer.echo(f"Compliance: {verdict}")
        typer.echo(f"Rule-based: {rule_verdict}  |  LLM review: {'PASS' if report.passed else 'FAIL'}")
        typer.echo(f"Errors: {report.error_count}  |  Warnings: {report.warning_count}")
        if report.violations:
            typer.echo(f"\nViolations ({len(report.violations)}):")
            for v in report.violations:
                color = typer.colors.RED if v.severity == "error" else typer.colors.YELLOW
                typer.echo(typer.style(f"  [{v.severity.upper()}] {v.type}: {v.description}", fg=color))
        else:
            typer.echo("No violations found.")
        typer.echo(f"\nSummary: {report.summary}")
        if report.passed:
            typer.echo(f"\nNext: git apply .harness/patches/{contract_id.upper()}.diff → harness validate")
        else:
            typer.echo("\nCompliance FAILED. Task returned to IMPLEMENTING. Fix the patch and re-run.")
    else:
        from harness.services.validation_service import _rule_based_check
        typer.echo("No API key — running rule-based check only (no LLM semantic review).")
        transition(task, TaskStatus.CHECKING_COMPLIANCE, db)
        rule_violations = _rule_based_check(dict(c), patch["diff_text"])
        rule_passed = not any(v.severity == "error" for v in rule_violations)
        verdict = "PASS" if rule_passed else "FAIL"
        summary = f"Rule-based {verdict}. {len(rule_violations)} violation(s). No LLM review."
        report_id = db.new_compliance_report_id()
        db.create_compliance_report({
            "id": report_id,
            "contract_id": contract_id.upper(),
            "patch_id": patch["id"],
            "passed": int(rule_passed),
            "violations_json": json.dumps([v.model_dump() for v in rule_violations]),
            "summary": summary,
            "created_at": now_iso(),
        })
        checking = {"id": task["id"], "status": TaskStatus.CHECKING_COMPLIANCE}
        if rule_passed:
            transition(checking, TaskStatus.VALIDATING, db)
            typer.echo(f"Compliance: PASS (rule-based only)")
            if rule_violations:
                for v in rule_violations:
                    typer.echo(f"  [{v.severity.upper()}] {v.type}: {v.description}")
            typer.echo(f"\nNext: git apply .harness/patches/{contract_id.upper()}.diff → harness validate")
        else:
            transition(checking, TaskStatus.IMPLEMENTING, db)
            typer.echo("Compliance: FAIL")
            for v in rule_violations:
                typer.echo(f"  [{v.severity.upper()}] {v.type}: {v.description}")
            typer.echo("\nCompliance FAILED. Task returned to IMPLEMENTING.")


# ---------------------------------------------------------------------------
# harness validate
# ---------------------------------------------------------------------------

@app.command()
def validate() -> None:
    """Run validation commands from config (empty list = auto-pass)."""
    _, config, db = _get_ctx()
    task = _get_active_task_or_exit(db)
    try:
        assert_command_allowed("validate", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    current = TaskStatus(task["status"])
    if current == TaskStatus.CHECKING_COMPLIANCE:
        transition(task, TaskStatus.VALIDATING, db)
        task = db.get_active_task()

    if not config.validate_commands:
        typer.echo("No validate_commands configured — auto-PASS.")
        validating = {"id": task["id"], "status": TaskStatus.VALIDATING}
        transition(validating, TaskStatus.DONE, db)
        typer.echo("Task → DONE")
        typer.echo("Next: harness remember")
        return

    all_passed = True
    for cmd in config.validate_commands:
        typer.echo(f"Running: {cmd}")
        result = subprocess.run(cmd, shell=True)
        if result.returncode != 0:
            typer.echo(f"  FAIL (exit {result.returncode})")
            all_passed = False
        else:
            typer.echo("  PASS")

    validating = {"id": task["id"], "status": TaskStatus.VALIDATING}
    if all_passed:
        transition(validating, TaskStatus.DONE, db)
        typer.echo("\nAll validation commands passed.")
        typer.echo("Next: harness remember")
    else:
        transition(validating, TaskStatus.IMPLEMENTING, db)
        typer.echo("\nValidation FAILED. Task returned to IMPLEMENTING.")


# ---------------------------------------------------------------------------
# harness remember
# ---------------------------------------------------------------------------

@app.command()
def remember() -> None:
    """Extract and save architectural lessons from the completed task via LLM."""
    _, config, db = _get_ctx()
    task = db.get_latest_task()
    if task is None:
        _abort("No task found. Run 'harness start' first.")
    task = dict(task)
    try:
        assert_command_allowed("remember", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    llm = _get_llm(config)
    if llm is not None:
        from harness.services.memory_service import write_memory
        typer.echo("Extracting lessons via LLM...")
        try:
            saved_entries = write_memory(task, llm, db, config)
        except Exception as e:
            _abort(f"Memory extraction failed: {e}")
        typer.echo(f"\nSaved {len(saved_entries)} memories:")
        for entry in saved_entries:
            val = json.loads(entry["value_json"])
            lesson = val.get("lesson", str(val)) if isinstance(val, dict) else str(val)
            typer.echo(f"  {entry['type']:<25} {entry['key']:<35} \"{lesson[:50]}\"")
    else:
        typer.echo("[STUB] No API key found — saving example memories.")
        stub_memories = [
            ("lesson", "scope_tip", "Keep entity-only tasks isolated from service layer"),
            ("project_standard", "api_dto_policy", "API always uses DTO pattern"),
            ("architecture_rule", "validation_location", "Validation happens at service boundary"),
        ]
        for mem_type, key, value in stub_memories:
            now = now_iso()
            db.upsert_memory({
                "id": Database.new_memory_id(),
                "type": mem_type,
                "scope": config.project_name,
                "key": key,
                "value_json": json.dumps(value),
                "source_task_id": task["id"],
                "applied_count": 0,
                "last_applied_at": None,
                "created_at": now,
                "updated_at": now,
            })
        typer.echo(f"\nSaved {len(stub_memories)} memories:")
        for mem_type, key, value in stub_memories:
            typer.echo(f"  {mem_type:<20} {key:<30} \"{value}\"")


# ---------------------------------------------------------------------------
# harness run  (full auto-loop via runtime)
# ---------------------------------------------------------------------------


@app.command()
def run(requirement: str) -> None:
    """Run the full harness workflow end-to-end automatically (requires API key)."""
    harness_dir, config, db = _get_ctx()
    llm = _get_llm(config)

    try:
        task = create_task(requirement, db)
    except ValueError as e:
        _abort(str(e))

    typer.echo(f"Task {task['id']}: {task['title']}")
    typer.echo("Running...")

    from harness.runtime import run_until_pause
    result = run_until_pause(task["id"], harness_dir, config, db, llm)
    _render_runtime_result(result)


def _render_runtime_result(result) -> None:
    """Rich-formatted display of a RuntimeResult."""
    from harness.runtime import PauseReason
    paused_at = result.paused_at

    if paused_at == PauseReason.DONE:
        typer.echo(f"\nDone. Task {result.task_id} complete.")
        if result.patch_file:
            typer.echo(f"Patch: {result.patch_file}")
            typer.echo(f"Apply with: git apply {result.patch_file}")
    elif paused_at == PauseReason.PATCH_APPROVAL_REQUIRED:
        typer.echo(f"\nPaused: patch ready for review.")
        typer.echo(result.message)
        if result.contract_id:
            typer.echo(f"Next: harness check {result.contract_id}")
    elif paused_at == PauseReason.HUMAN_DECISIONS_REQUIRED:
        typer.echo(f"\nPaused: human decisions required.")
        typer.echo(result.message)
        if result.conflicts:
            typer.echo("\n[WARNING] Conflicts with project memory:")
            for c in result.conflicts:
                typer.echo(f"  ⚠  {c.get('warning', '')}")
        typer.echo("Next: harness decisions → harness answer → harness approve")
    elif paused_at == PauseReason.COMPLIANCE_FAILED:
        typer.echo(f"\nPaused: compliance failed after {result.compliance_retries} attempt(s).")
        typer.echo(result.message)
    elif paused_at == PauseReason.VALIDATION_FAILED:
        typer.echo(f"\nPaused: validation failed.")
        typer.echo(result.message)
    elif paused_at == PauseReason.LLM_UNAVAILABLE:
        typer.echo(f"\nPaused: LLM unavailable.")
        typer.echo(result.message)
    else:
        typer.echo(f"\nPaused: {paused_at}")
        typer.echo(result.message)
        if result.error:
            typer.echo(f"Error: {result.error}")


# ---------------------------------------------------------------------------
# harness report
# ---------------------------------------------------------------------------

@app.command()
def report(
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="Output file path (default: .harness/reports/<task-id>.md)")] = None,
) -> None:
    """Export a markdown report of the current (or last) task."""
    harness_dir, config, db = _get_ctx()
    task = db.get_latest_task()
    if task is None:
        _abort("No task found. Run 'harness start' first.")
    task = dict(task)

    decisions = db.get_decisions(task["id"])
    contract = db.get_latest_contract(task["id"])
    patch = db.get_latest_patch(contract["id"]) if contract else None
    compliance = db.get_latest_compliance_report(contract["id"]) if contract else None

    lines: list[str] = []
    lines.append(f"# Harness Report: {task['title']}\n")
    lines.append(f"**Task ID:** {task['id']}  ")
    lines.append(f"**Status:** {task['status']}  ")
    lines.append(f"**Created:** {task['created_at']}\n")
    lines.append("---\n")

    lines.append("## Requirement\n")
    lines.append(f"{task['raw_requirement']}\n")

    lines.append("## Decisions\n")
    if decisions:
        total = len(decisions)
        answered = sum(1 for d in decisions if d["status"] in ("answered", "approved"))
        approved = sum(1 for d in decisions if d["status"] == "approved")
        lines.append(f"Coverage: {answered}/{total} answered, {approved}/{total} approved\n")
        lines.append("| ID | Category | Status | Question | Answer |")
        lines.append("|----|----------|--------|----------|--------|")
        for d in decisions:
            ans = (d["selected_answer"] or "").replace("|", "\\|")
            q = d["question"].replace("|", "\\|")
            lines.append(f"| {d['id']} | {d['category']} | {d['status']} | {q} | {ans} |")
        lines.append("")
    else:
        lines.append("No decisions recorded.\n")

    if contract:
        lines.append("## Contract\n")
        lines.append(f"**Contract ID:** {contract['id']}  ")
        lines.append(f"**Scope:** {contract['scope']}\n")
        allowed = json.loads(contract["allowed_files_json"])
        lines.append(f"**Allowed files:** {', '.join(allowed)}\n")
        forbidden = json.loads(contract["forbidden_json"])
        lines.append(f"**Forbidden patterns:** {', '.join(forbidden)}\n")

    if patch:
        lines.append("## Patch\n")
        lines.append(f"```diff\n{patch['diff_text']}\n```\n")

    if compliance:
        violations = json.loads(compliance["violations_json"])
        verdict = "PASS" if compliance["passed"] else "FAIL"
        lines.append("## Compliance\n")
        lines.append(f"**Result:** {verdict}  ")
        lines.append(f"**Summary:** {compliance['summary']}\n")
        if violations:
            lines.append("| Severity | Type | Description |")
            lines.append("|----------|------|-------------|")
            for v in violations:
                lines.append(f"| {v.get('severity','').upper()} | {v.get('type','')} | {v.get('description','')} |")
            lines.append("")

    md_content = "\n".join(lines)

    if output:
        out_path = Path(output)
    else:
        reports_dir = harness_dir / "reports"
        reports_dir.mkdir(exist_ok=True)
        out_path = reports_dir / f"{task['id']}.md"

    out_path.write_text(md_content)
    typer.echo(f"Report written to {out_path}")


# ---------------------------------------------------------------------------
# harness memory list
# ---------------------------------------------------------------------------

@memory_app.command("list")
def memory_list(
    type_filter: Annotated[Optional[str], typer.Option("--type")] = None,
    scope_filter: Annotated[Optional[str], typer.Option("--scope")] = None,
) -> None:
    """List stored memories."""
    _, _, db = _get_ctx()
    rows = db.list_memory(type_filter, scope_filter)

    if not rows:
        typer.echo("No memories stored yet.")
        return

    table = Table(title="Memory")
    table.add_column("ID", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Scope")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_column("Applied", justify="right")
    for row in rows:
        value = json.loads(row["value_json"])
        lesson = value.get("lesson", str(value)) if isinstance(value, dict) else str(value)
        applied = str(row["applied_count"]) if "applied_count" in row.keys() else "0"
        table.add_row(row["id"], row["type"], row["scope"], row["key"], lesson[:55], applied)
    rprint(table)


@memory_app.command("search")
def memory_search(
    query: str,
    type_filter: Annotated[Optional[str], typer.Option("--type")] = None,
) -> None:
    """Search memories by keyword (matches key and value)."""
    _, config, db = _get_ctx()
    from harness.services.memory_service import search_memory
    rows = search_memory(db, query, type_filter=type_filter, scope_filter=config.project_name)

    if not rows:
        typer.echo(f"No memories matching '{query}'.")
        return

    table = Table(title=f"Memory search: '{query}'")
    table.add_column("ID", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for row in rows:
        value = json.loads(row["value_json"])
        lesson = value.get("lesson", str(value)) if isinstance(value, dict) else str(value)
        table.add_row(row["id"], row["type"], row["key"], lesson[:60])
    rprint(table)


@memory_app.command("delete")
def memory_delete(memory_id: str) -> None:
    """Delete a memory entry by ID."""
    _, _, db = _get_ctx()
    deleted = db.delete_memory(memory_id.upper())
    if deleted:
        typer.echo(f"Memory {memory_id.upper()} deleted.")
    else:
        _abort(f"Memory {memory_id.upper()} not found.")


# ---------------------------------------------------------------------------
# harness config set
# ---------------------------------------------------------------------------

_SETTABLE_FIELDS = {"llm_provider", "llm_model", "project_name"}
_INT_FIELDS = {"max_tokens", "llm_retries", "context_max_depth"}


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set a config value (llm_provider, llm_model, project_name, max_tokens, llm_retries, validate_commands)."""
    harness_dir, config, _ = _get_ctx()

    if key == "validate_commands":
        config.validate_commands = [v.strip() for v in value.split(",") if v.strip()]
    elif key in _INT_FIELDS:
        try:
            config = config.model_copy(update={key: int(value)})
        except ValueError:
            _abort(f"'{key}' must be an integer, got: {value!r}")
    elif key in _SETTABLE_FIELDS:
        config = config.model_copy(update={key: value})
    else:
        all_keys = ", ".join(sorted(_SETTABLE_FIELDS | _INT_FIELDS | {"validate_commands"}))
        _abort(f"Unknown config key '{key}'. Settable: {all_keys}")

    save_config(harness_dir, config)
    typer.echo(f"Config updated: {key} = {value}")


# ---------------------------------------------------------------------------
# harness ui
# ---------------------------------------------------------------------------

@app.command()
def ui(
    port: Annotated[int, typer.Option("--port", "-p", help="Port to run on")] = 8501,
) -> None:
    """Open the Harness web dashboard (Streamlit)."""
    import subprocess
    import sys
    from pathlib import Path
    app_path = Path(__file__).parent / "app.py"
    typer.echo(f"Starting Harness UI at http://localhost:{port}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port)],
        check=False,
    )


# ---------------------------------------------------------------------------
# harness serve
# ---------------------------------------------------------------------------

@app.command()
def serve() -> None:
    """Start the Harness MCP server (stdio transport for Claude Code / Cursor integration)."""
    from harness.server import run as run_server
    typer.echo("Starting Harness MCP server (stdio)...", err=True)
    run_server()


# ---------------------------------------------------------------------------
# harness trace
# ---------------------------------------------------------------------------

@app.command()
def trace(
    task_id: Annotated[Optional[str], typer.Argument(help="Task ID (default: latest)")] = None,
) -> None:
    """Show event trace (state transitions + LLM calls) for a task."""
    _, _, db = _get_ctx()

    if task_id:
        task_row = db.get_task(task_id.upper())
    else:
        task_row = db.get_latest_task()

    if task_row is None:
        _abort("No task found.")

    task_row = dict(task_row)
    events = db.get_events(task_row["id"])

    if not events:
        typer.echo(f"No events recorded for task {task_row['id']}.")
        typer.echo("(Events are recorded from future transitions — run harness start to begin.)")
        return

    typer.echo(f"Event trace for task {task_row['id']}: {task_row['title']}\n")
    table = Table(show_header=True)
    table.add_column("Time", style="dim", width=12)
    table.add_column("Type", width=18)
    table.add_column("From → To / Prompt", width=45)
    table.add_column("ms", justify="right", width=6)

    for ev in events:
        ts = ev["created_at"][11:19] if ev["created_at"] else ""
        ev_type = ev["event_type"] or ""
        if ev_type == "state_transition":
            detail = f"{ev['from_state']} → {ev['to_state']}"
        elif ev_type == "llm_call":
            detail = ev["prompt_name"] or ""
        else:
            detail = ev["tool_name"] or ""
        ms_val = str(ev["duration_ms"]) if ev["duration_ms"] is not None else ""
        table.add_row(ts, ev_type, detail, ms_val)

    rprint(table)


# ---------------------------------------------------------------------------
# harness history
# ---------------------------------------------------------------------------

@app.command()
def history(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max tasks to show")] = 20,
) -> None:
    """Browse task history (all tasks, newest first)."""
    _, _, db = _get_ctx()
    tasks = db.list_tasks(limit=limit)

    if not tasks:
        typer.echo("No tasks found.")
        return

    table = Table(title=f"Task History (last {limit})")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Status", style="bold")
    table.add_column("Decisions")
    table.add_column("Created")

    for t in tasks:
        decisions = db.get_decisions(t["id"])
        total = len(decisions)
        approved = sum(1 for d in decisions if d["status"] == "approved")
        status_color = "green" if t["status"] == "DONE" else "yellow"
        created = t["created_at"][:10] if t["created_at"] else "?"
        table.add_row(
            t["id"],
            t["title"][:45] + ("…" if len(t["title"]) > 45 else ""),
            f"[{status_color}]{t['status']}[/{status_color}]",
            f"{approved}/{total}",
            created,
        )
    rprint(table)


# ---------------------------------------------------------------------------
# harness eval
# ---------------------------------------------------------------------------

@app.command()
def eval(
    task_id: Annotated[Optional[str], typer.Argument(help="Task ID (default: latest)")] = None,
) -> None:
    """Show or compute evaluation metrics for a task."""
    _, _, db = _get_ctx()

    if task_id is None:
        task_row = db.get_latest_task()
        if task_row is None:
            _abort("No task found.")
        task_id = task_row["id"]

    task_row = db.get_task(task_id.upper())
    if task_row is None:
        _abort(f"Task {task_id} not found.")
    task = dict(task_row)

    # Check if evaluation already exists
    existing = db.get_evaluation(task["id"])
    if existing is None:
        # Compute on demand
        if task["status"] != "DONE":
            typer.echo(f"Task {task['id']} is not DONE (status: {task['status']}). Partial metrics only.")
        from harness.services.evaluation_service import compute_task_evaluation
        ev = compute_task_evaluation(task, db)
    else:
        from harness.schemas.evaluation import TaskEvaluation
        ev = TaskEvaluation.model_validate_json(existing["metrics_json"])

    typer.echo(f"\nEvaluation: {ev.id}  Task: {ev.task_id}")
    typer.echo("─" * 60)

    dc = ev.decision_coverage
    typer.echo(f"Decision Coverage:  {dc.answered}/{dc.total_decisions} answered ({dc.coverage_pct}%)")
    typer.echo(f"Approval Rate:      {dc.approved}/{dc.total_decisions} approved ({dc.approval_pct}%)")
    typer.echo(f"Categories covered: {', '.join(dc.categories_covered) or '(none)'}")
    if dc.categories_missing:
        typer.echo(f"Categories missing: {', '.join(dc.categories_missing)}")

    typer.echo("")
    co = ev.compliance
    first_try = "YES" if co.passed_on_first_try else "NO"
    typer.echo(f"Compliance checks:  {co.total_checks} total, passed first try: {first_try}")
    typer.echo(f"Retries:            {co.total_retries}")
    typer.echo(f"Final violations:   {co.final_error_violations} errors, {co.final_warning_violations} warnings")

    typer.echo("")
    typer.echo(f"Memories written:   {ev.memory.memories_written}")
    typer.echo(f"Cycle time:         {ev.cycle_time_seconds:.0f}s ({ev.cycle_time_seconds/60:.1f}m)")
    typer.echo(f"Contract:           {ev.contract_id or '(none)'}")
