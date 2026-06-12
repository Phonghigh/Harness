import subprocess
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from harness.config import HarnessConfig
from harness.db import Database
from harness.llm import LLMAdapter
from harness.schemas.task import TaskStatus


class PauseReason(StrEnum):
    HUMAN_DECISIONS_REQUIRED = "human_decisions_required"
    CONTRACT_APPROVAL_REQUIRED = "contract_approval_required"
    PATCH_APPROVAL_REQUIRED = "patch_approval_required"
    COMPLIANCE_FAILED = "compliance_failed"
    VALIDATION_FAILED = "validation_failed"
    LLM_UNAVAILABLE = "llm_unavailable"
    DONE = "done"
    ERROR = "error"


class RuntimeResult(BaseModel):
    task_id: str
    final_status: str
    paused_at: PauseReason
    message: str
    contract_id: str | None = None
    patch_file: str | None = None
    compliance_retries: int = 0
    conflicts: list[dict] = []
    error: str | None = None


def run_until_pause(
    task_id: str,
    harness_dir: Path,
    config: HarnessConfig,
    db: Database,
    llm: LLMAdapter | None,
    *,
    max_compliance_retries: int = 3,
    auto_answer: bool = True,
) -> RuntimeResult:
    """Drive the task forward until a human gate or terminal state is reached.

    Returns a RuntimeResult describing why execution paused and what to do next.
    """
    from harness.services.contract_service import approve_contract, build_contract
    from harness.services.decision_service import answer_decision, approve_decisions, auto_answer_decisions
    from harness.services.implementation_service import approve_patch, implement, reimplement
    from harness.services.memory_service import write_memory
    from harness.services.task_service import run_interrogate
    from harness.services.validation_service import check_compliance
    from harness.state_machine import transition

    compliance_retries = 0
    contract = None

    while True:
        task = dict(db.get_task(task_id))
        status = TaskStatus(task["status"])

        # --- INTAKE: generate decisions ---
        if status == TaskStatus.INTAKE:
            if llm is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.LLM_UNAVAILABLE,
                    message="LLM required for interrogation. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
                )
            run_interrogate(task, llm, db)
            continue

        # --- WAITING_FOR_DECISIONS: auto-answer then approve ---
        if status == TaskStatus.WAITING_FOR_DECISIONS:
            if llm is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.LLM_UNAVAILABLE,
                    message="LLM required for auto-answering decisions.",
                )
            decisions = db.get_decisions(task_id)
            if auto_answer:
                pending = [dict(d) for d in decisions if d["status"] == "pending"]
                if pending:
                    auto_answer_decisions(task, [dict(d) for d in decisions], llm, db)
                    task = dict(db.get_task(task_id))

            decision_ids = [d["id"] for d in db.get_decisions(task_id)]
            all_approved, conflicts = approve_decisions(decision_ids, task, db)
            if not all_approved:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=TaskStatus(dict(db.get_task(task_id))["status"]).value,
                    paused_at=PauseReason.HUMAN_DECISIONS_REQUIRED,
                    message="Some decisions could not be auto-answered. Human input required.",
                    conflicts=conflicts,
                )
            continue

        # --- DECISIONS_APPROVED: build contract ---
        if status == TaskStatus.DECISIONS_APPROVED:
            if llm is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.LLM_UNAVAILABLE,
                    message="LLM required for contract generation.",
                )
            contract = build_contract(task, db, llm)
            continue

        # --- WAITING_FOR_CONTRACT_APPROVAL: auto-approve in runtime, or pause ---
        if status == TaskStatus.WAITING_FOR_CONTRACT_APPROVAL:
            # In the runtime, auto-approve the contract so the loop can continue.
            # The CLI commands `harness contract-approve` / `harness contract-reject`
            # let humans control this step interactively.
            if contract is None:
                c = db.get_latest_contract(task_id)
                if c:
                    contract = dict(c)
            if contract is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.ERROR,
                    message="No contract found to approve.",
                    error="missing contract",
                )
            approve_contract(task, contract["id"], db)
            continue

        # --- CONTRACT_READY: generate patch, then loop to WAITING_FOR_PATCH_APPROVAL ---
        if status == TaskStatus.CONTRACT_READY:
            if llm is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.LLM_UNAVAILABLE,
                    message="LLM required for patch generation.",
                )
            if contract is None:
                contract = db.get_latest_contract(task_id)
                if contract:
                    contract = dict(contract)
            implement(task, contract, harness_dir, llm, db)
            continue

        # --- WAITING_FOR_PATCH_APPROVAL: pause so human can review the patch ---
        if status == TaskStatus.WAITING_FOR_PATCH_APPROVAL:
            if contract is None:
                c = db.get_latest_contract(task_id)
                if c:
                    contract = dict(c)
            patch = db.get_latest_patch(contract["id"]) if contract else None
            patch_file_str = str(harness_dir / "patches" / f"{contract['id']}.diff") if contract else None
            return RuntimeResult(
                task_id=task_id,
                final_status=status.value,
                paused_at=PauseReason.PATCH_APPROVAL_REQUIRED,
                message=(
                    f"Patch generated: {patch_file_str}. "
                    "Review the patch, then run: harness apply"
                ),
                contract_id=contract["id"] if contract else None,
                patch_file=patch_file_str,
            )

        # --- IMPLEMENTING: compliance check with retry ---
        if status == TaskStatus.IMPLEMENTING:
            if contract is None:
                c = db.get_latest_contract(task_id)
                if c:
                    contract = dict(c)
            if contract is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.ERROR,
                    message="No contract found for compliance check.",
                    error="missing contract",
                )
            patch = db.get_latest_patch(contract["id"])
            if patch is None:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=status.value,
                    paused_at=PauseReason.ERROR,
                    message="No patch found for compliance check.",
                    error="missing patch",
                )

            report = check_compliance(task, contract, patch["diff_text"], harness_dir, llm, db)
            if report.passed:
                continue

            compliance_retries += 1
            if compliance_retries >= max_compliance_retries:
                return RuntimeResult(
                    task_id=task_id,
                    final_status=TaskStatus.IMPLEMENTING.value,
                    paused_at=PauseReason.COMPLIANCE_FAILED,
                    message=(
                        f"Compliance failed after {compliance_retries} attempts. "
                        f"Review {harness_dir}/patches/{contract['id']}.diff manually, "
                        f"then run: harness check {contract['id']}"
                    ),
                    contract_id=contract["id"],
                    compliance_retries=compliance_retries,
                )

            # Re-generate patch and loop back
            task = dict(db.get_task(task_id))
            reimplement(task, contract, harness_dir, llm, db, compliance_summary=report.summary)
            continue

        # --- CHECKING_COMPLIANCE: should resolve quickly (transition handled by service) ---
        if status == TaskStatus.CHECKING_COMPLIANCE:
            # This state is transient — services handle the transition. Yield to next loop.
            continue

        # --- VALIDATING: run shell validation commands ---
        if status == TaskStatus.VALIDATING:
            if not config.validate_commands:
                validating = {"id": task_id, "status": TaskStatus.VALIDATING}
                transition(validating, TaskStatus.DONE, db)
                continue

            all_passed = True
            for cmd in config.validate_commands:
                rc = subprocess.run(cmd, shell=True, capture_output=True).returncode
                if rc != 0:
                    all_passed = False
                    break

            validating = {"id": task_id, "status": TaskStatus.VALIDATING}
            if all_passed:
                transition(validating, TaskStatus.DONE, db)
                continue
            else:
                transition(validating, TaskStatus.IMPLEMENTING, db)
                return RuntimeResult(
                    task_id=task_id,
                    final_status=TaskStatus.IMPLEMENTING.value,
                    paused_at=PauseReason.VALIDATION_FAILED,
                    message="Validation commands failed. Fix the issues and re-run.",
                    contract_id=contract["id"] if contract else None,
                )

        # --- DONE: extract memories (non-fatal), return ---
        if status == TaskStatus.DONE:
            if llm is not None:
                try:
                    write_memory(task, llm, db, config)
                except Exception:
                    pass
            return RuntimeResult(
                task_id=task_id,
                final_status=TaskStatus.DONE.value,
                paused_at=PauseReason.DONE,
                message="Task complete.",
                contract_id=contract["id"] if contract else None,
                compliance_retries=compliance_retries,
            )

        # Unknown state — bail out
        return RuntimeResult(
            task_id=task_id,
            final_status=status.value,
            paused_at=PauseReason.ERROR,
            message=f"Runtime reached unexpected state: {status}",
            error=f"unexpected_state:{status}",
        )
