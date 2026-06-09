from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

DECISION_CATEGORIES: list[str] = [
    "product_behavior",
    "data_model",
    "api_contract",
    "business_rules",
    "architecture_pattern",
    "state_lifecycle",
    "validation",
    "error_handling",
    "security_permission",
    "persistence_transaction",
    "performance_concurrency",
    "observability",
    "testing",
    "migration_compatibility",
    "implementation_scope",
]


class DecisionStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    APPROVED = "approved"


class Decision(BaseModel):
    id: str  # e.g. D001
    task_id: str
    category: str
    question: str
    options: list[str]
    recommendation: str | None = None
    selected_answer: str | None = None
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: datetime
    updated_at: datetime


class DecisionMapItem(BaseModel):
    """Shape of each decision item in interrogator LLM output."""

    category: str
    question: str
    options: list[str]
    recommendation: str | None = None


class DecisionMap(BaseModel):
    """Full interrogator LLM response."""

    decisions: list[DecisionMapItem]
    rationale: str
