import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.table import Table

from harness.config import EnvSettings, HarnessConfig, load_config, save_config
from harness.db import Database, now_iso
from harness.llm import LLMAdapter, get_adapter
from harness.schemas.task import TaskStatus
from harness.services.contract_service import build_contract
from harness.services.decision_service import (
    answer_decision,
    approve_decisions,
    generate_stub_decisions,
    list_decisions,
)
from harness.services.implementation_service import implement as svc_implement
from harness.services.task_service import (
    create_task,
    get_active_task_or_exit,
    run_interrogate,
)
from harness.services.validation_service import check_compliance, run_validate
from harness.state_machine import WrongStateError, assert_command_allowed

app = typer.Typer(no_args_is_help=True, help="Architect-Driven Coding Harness")
memory_app = typer.Typer(no_args_is_help=True, help="Memory commands")
app.add_typer(memory_app, name="memory")


def _get_ctx() -> tuple[Path, HarnessConfig, Database, LLMAdapter | None]:
    harness_dir, config = load_config()
    db = Database(harness_dir / "harness.db")
    env = EnvSettings()
    llm = get_adapter(config, env)
    return harness_dir, config, db, llm


def _abort(msg: str) -> None:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)


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
    _, _, db, llm = _get_ctx()
    task = create_task(requirement, db)
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
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)

    typer.echo(f"Task {task['id']}: {task['title']} [{task['status']}]")

    decisions = db.get_decisions(task["id"])
    if decisions:
        typer.echo(f"\nDecisions ({len(decisions)} total):")
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
    """Generate decision map for the active task."""
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("interrogate", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    if llm is None:
        typer.echo("[STUB] No API key — using stub decisions.")
        decisions = generate_stub_decisions(task, db)
    else:
        typer.echo("Interrogating requirement...")
        try:
            decisions = run_interrogate(task, llm, db)
        except RuntimeError as e:
            _abort(str(e))

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
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
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
    decision_id: str,
    answer_text: Annotated[Optional[str], typer.Argument()] = None,
) -> None:
    """Record an answer for a decision."""
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("answer", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

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
    decision_ids: Annotated[list[str], typer.Argument()],
) -> None:
    """Approve one or more answered decisions."""
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("approve", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    all_approved = approve_decisions(decision_ids, task, db)
    for did in decision_ids:
        typer.echo(f"Decision {did.upper()} approved.")

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
    """Build implementation contract from approved decisions."""
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("contract", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    if llm is None:
        typer.echo("[STUB] No API key — using stub contract.")
    else:
        typer.echo("Building contract...")
    try:
        c = build_contract(task, db, llm)
    except RuntimeError as e:
        _abort(str(e))
    allowed = json.loads(c["allowed_files_json"])
    forbidden = json.loads(c["forbidden_json"])

    typer.echo(f"\nContract {c['id']} created.")
    typer.echo(f"Scope: {c['scope']}")
    typer.echo(f"\nAllowed files ({len(allowed)}):")
    for f in allowed:
        typer.echo(f"  {f}")
    typer.echo(f"\nForbidden patterns: {', '.join(forbidden)}")
    typer.echo(f"\nNext: harness implement {c['id']}")


# ---------------------------------------------------------------------------
# harness implement
# ---------------------------------------------------------------------------

@app.command()
def implement(contract_id: str) -> None:
    """Generate patch file from contract."""
    harness_dir, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("implement", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    c = db.get_contract(contract_id.upper())
    if c is None:
        _abort(f"Contract {contract_id} not found.")

    if llm is None:
        typer.echo("[STUB] No API key — generating placeholder patch.")
    else:
        typer.echo("Generating patch...")

    try:
        patch = svc_implement(dict(task), dict(c), db, harness_dir, llm)
    except RuntimeError as e:
        _abort(str(e))

    patch_file = harness_dir / "patches" / f"{contract_id.upper()}.diff"
    added = sum(1 for l in patch["diff_text"].splitlines() if l.startswith("+") and not l.startswith("+++"))
    typer.echo(f"Patch saved: {patch_file}")
    typer.echo(f"Lines added: {added}")
    typer.echo(f"\nNext: harness check {contract_id.upper()}")


# ---------------------------------------------------------------------------
# harness check
# ---------------------------------------------------------------------------

@app.command()
def check(contract_id: str) -> None:
    """Run compliance check on patch."""
    _, _, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
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

    typer.echo("Checking compliance...")
    report = check_compliance(dict(task), dict(c), dict(patch), db, llm)

    status_str = "PASS" if report.passed else "FAIL"
    typer.echo(f"\nCompliance: {status_str}")
    typer.echo(f"Rule-based: {'PASS' if report.rule_based_passed else 'FAIL'}")
    if report.llm_review:
        typer.echo(f"LLM review: {report.llm_review[:120]}")

    if report.violations:
        typer.echo("\nViolations:")
        for v in report.violations:
            line = f"  {v.severity.upper():<8} {v.type:<20} {v.description}"
            if v.line_ref:
                line += f"  ({v.line_ref})"
            typer.echo(line)
    else:
        typer.echo("No violations found.")

    if report.passed:
        typer.echo(f"\nNext: git apply .harness/patches/{contract_id.upper()}.diff → harness validate")
    else:
        typer.echo("\nTask returned to IMPLEMENTING. Fix and re-run 'harness implement'.")


# ---------------------------------------------------------------------------
# harness validate
# ---------------------------------------------------------------------------

@app.command()
def validate() -> None:
    """Run validation commands from config (empty list = auto-pass)."""
    _, config, db, llm = _get_ctx()
    task = get_active_task_or_exit(db)
    try:
        assert_command_allowed("validate", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    typer.echo("Running validation...")
    passed = run_validate(dict(task), config.validate_commands, db)
    if passed:
        typer.echo("All validation commands passed. Task → DONE")
        typer.echo("Next: harness remember")
    else:
        typer.echo("Validation FAILED. Task returned to IMPLEMENTING.")


# ---------------------------------------------------------------------------
# harness remember
# ---------------------------------------------------------------------------

@app.command()
def remember() -> None:
    """Extract and save lessons from the completed task (stub)."""
    _, config, db, llm = _get_ctx()
    task = db.get_latest_task()
    if task is None:
        _abort("No task found. Run 'harness start' first.")
    task = dict(task)
    try:
        assert_command_allowed("remember", TaskStatus(task["status"]))
    except WrongStateError as e:
        _abort(str(e))

    typer.echo("[STUB] Extracting lessons...")

    stub_memories = [
        ("lesson", "scope_tip", "Keep entity-only tasks isolated from service layer"),
        ("project_standard", "api_dto_policy", "API always uses DTO pattern"),
        ("architecture_rule", "validation_location", "Validation happens at service boundary"),
    ]

    saved = 0
    for mem_type, key, value in stub_memories:
        now = now_iso()
        db.upsert_memory({
            "id": Database.new_memory_id(),
            "type": mem_type,
            "scope": config.project_name,
            "key": key,
            "value_json": json.dumps(value),
            "created_at": now,
            "updated_at": now,
        })
        saved += 1

    typer.echo(f"\nSaved {saved} memories:")
    for mem_type, key, value in stub_memories:
        typer.echo(f"  {mem_type:<20} {key:<30} \"{value}\"")


# ---------------------------------------------------------------------------
# harness memory list
# ---------------------------------------------------------------------------

@memory_app.command("list")
def memory_list(
    type_filter: Annotated[Optional[str], typer.Option("--type")] = None,
    scope_filter: Annotated[Optional[str], typer.Option("--scope")] = None,
) -> None:
    """List stored memories."""
    _, _, db, llm = _get_ctx()
    rows = db.list_memory(type_filter, scope_filter)

    if not rows:
        typer.echo("No memories stored yet.")
        return

    table = Table(title="Memory")
    table.add_column("Type", style="cyan")
    table.add_column("Scope")
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for row in rows:
        value = json.loads(row["value_json"])
        table.add_row(row["type"], row["scope"], row["key"], str(value)[:60])
    rprint(table)
