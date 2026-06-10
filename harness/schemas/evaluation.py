from datetime import datetime

from pydantic import BaseModel


class DecisionCoverageMetric(BaseModel):
    total_decisions: int
    answered: int
    approved: int
    coverage_pct: float
    approval_pct: float
    categories_covered: list[str]
    categories_missing: list[str]


class ComplianceMetric(BaseModel):
    total_checks: int
    passed_on_first_try: bool
    total_retries: int
    final_error_violations: int
    final_warning_violations: int


class MemoryMetric(BaseModel):
    memories_written: int


class TaskEvaluation(BaseModel):
    id: str                     # E001, E002 ...
    task_id: str
    contract_id: str | None
    decision_coverage: DecisionCoverageMetric
    compliance: ComplianceMetric
    memory: MemoryMetric
    cycle_time_seconds: float
    created_at: datetime
