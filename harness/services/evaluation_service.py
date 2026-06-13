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

    _write_evaluation_memories(eval_obj, task, db)
    return eval_obj


def _write_evaluation_memories(evaluation, task: dict, db: Database) -> None:
    """Derive and write structured memories from evaluation metrics."""
    from harness.db import now_iso
    from harness.services.memory_service import write_event_memory

    class _FakeConfig:
        project_name: str = task.get("title", "default")[:20]

    config = _FakeConfig()
    config.project_name = task.get("title", "default")[:20]

    # E1: Missing decision categories → interrogation_pattern memory
    missing = evaluation.decision_coverage.categories_missing
    if missing:
        from harness.db import Database as _DB
        now = now_iso()
        entry = {
            "id": _DB.new_memory_id(),
            "type": "interrogation_pattern",
            "scope": config.project_name,
            "key": f"missed_categories_{task['id']}",
            "value_json": json.dumps({
                "lesson": f"Task '{task.get('title', '')[:50]}' did not cover categories: {', '.join(missing)}",
                "context": "Consider these categories for similar future requirements",
            }),
            "category": "implementation_scope",
            "source_task_id": task.get("id"),
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now,
            "updated_at": now,
        }
        db.upsert_memory(entry)

    # E2: High retry count → compliance_pattern memory
    if evaluation.compliance.total_retries >= 2:
        write_event_memory("compliance_failure", {
            "violation_type": "high_retry_count",
            "description": (
                f"Contract for task '{task.get('title', '')}' needed "
                f"{evaluation.compliance.total_retries} retries — review constraints"
            ),
            "contract_id": evaluation.contract_id or "",
            "task_id": task.get("id"),
            "task_title": task.get("title", ""),
        }, db, config)

    # E3: First-pass success → lesson memory
    if evaluation.compliance.passed_on_first_try:
        write_event_memory("compliance_success", {
            "task_id": task.get("id"),
            "task_title": task.get("title", ""),
            "category": "implementation_scope",
        }, db, config)
