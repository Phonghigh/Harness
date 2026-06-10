from enum import StrEnum

from pydantic import BaseModel


class ViolationType(StrEnum):
    SCOPE_VIOLATION = "scope_violation"
    FORBIDDEN_PATTERN = "forbidden_pattern"
    MISSING_SPEC = "missing_spec"
    EXTRA_SCOPE = "extra_scope"


class Violation(BaseModel):
    type: ViolationType
    severity: str  # "error" | "warning"
    description: str
    line_ref: str | None = None


class ComplianceReport(BaseModel):
    contract_id: str
    patch_file: str
    passed: bool
    violations: list[Violation]
    summary: str
    rule_based_passed: bool
    llm_review: str | None = None
    error_count: int = 0
    warning_count: int = 0
