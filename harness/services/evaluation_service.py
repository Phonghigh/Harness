import json
from datetime import datetime, timezone

from harness.db import Database, now_iso
from harness.schemas.decision import DECISION_CATEGORIES
from harness.schemas.evaluation import (
    ComplianceMetric,
    DecisionCoverageMetric,
    MemoryMetric,
    TaskEvaluation,
)


def compute_task_evaluation(task: dict, db: Database) -> TaskEvaluation:
    """Compute evaluation metrics for a task and persist them."""
    decisions = [dict(r) for r in db.get_decisions(task["id"])]
    contract = db.get_latest_contract(task["id"])
    compliance_reports = [dict(r) for r in db.get_compliance_reports_for_task(task["id"])]
    all_memories = [dict(r) for r in db.list_memory()]

    # Decision coverage
    total = len(decisions)
    answered = sum(1 for d in decisions if d["status"] in ("answered", "approved"))
    approved_count = sum(1 for d in decisions if d["status"] == "approved")
    categories_used = {d["category"] for d in decisions}
    all_categories = set(DECISION_CATEGORIES)
    coverage_pct = round(answered / total * 100, 1) if total else 0.0
    approval_pct = round(approved_count / total * 100, 1) if total else 0.0

    decision_coverage = DecisionCoverageMetric(
        total_decisions=total,
        answered=answered,
        approved=approved_count,
        coverage_pct=coverage_pct,
        approval_pct=approval_pct,
        categories_covered=sorted(categories_used),
        categories_missing=sorted(all_categories - categories_used),
    )

    # Compliance metrics
    total_checks = len(compliance_reports)
    passed_on_first = bool(compliance_reports) and bool(compliance_reports[0]["passed"])
    retries = max(0, total_checks - 1)
    final_violations = []
    if compliance_reports:
        last = compliance_reports[-1]
        try:
            final_violations = json.loads(last.get("violations_json") or "[]")
        except json.JSONDecodeError:
            final_violations = []
    final_errors = sum(1 for v in final_violations if v.get("severity") == "error")
    final_warnings = sum(1 for v in final_violations if v.get("severity") == "warning")

    compliance = ComplianceMetric(
        total_checks=total_checks,
        passed_on_first_try=passed_on_first,
        total_retries=retries,
        final_error_violations=final_errors,
        final_warning_violations=final_warnings,
    )

    # Memory metrics (count memories sourced from this task)
    task_memories = [m for m in all_memories if m.get("source_task_id") == task["id"]]
    memory = MemoryMetric(memories_written=len(task_memories))

    # Cycle time
    try:
        created = datetime.fromisoformat(task["created_at"])
        updated = datetime.fromisoformat(task["updated_at"])
        cycle_secs = (updated - created).total_seconds()
    except (ValueError, KeyError):
        cycle_secs = 0.0

    eval_obj = TaskEvaluation(
        id=db.new_evaluation_id(),
        task_id=task["id"],
        contract_id=contract["id"] if contract else None,
        decision_coverage=decision_coverage,
        compliance=compliance,
        memory=memory,
        cycle_time_seconds=cycle_secs,
        created_at=datetime.now(timezone.utc),
    )

    db.create_evaluation({
        "id": eval_obj.id,
        "task_id": eval_obj.task_id,
        "contract_id": eval_obj.contract_id,
        "metrics_json": eval_obj.model_dump_json(),
        "created_at": now_iso(),
    })

    return eval_obj
