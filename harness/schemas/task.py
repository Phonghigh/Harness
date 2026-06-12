from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class TaskStatus(StrEnum):
    INTAKE = "INTAKE"
    INTERROGATING = "INTERROGATING"
    WAITING_FOR_DECISIONS = "WAITING_FOR_DECISIONS"
    DECISIONS_APPROVED = "DECISIONS_APPROVED"
    WAITING_FOR_CONTRACT_APPROVAL = "WAITING_FOR_CONTRACT_APPROVAL"
    CONTRACT_READY = "CONTRACT_READY"
    WAITING_FOR_PATCH_APPROVAL = "WAITING_FOR_PATCH_APPROVAL"
    IMPLEMENTING = "IMPLEMENTING"
    CHECKING_COMPLIANCE = "CHECKING_COMPLIANCE"
    VALIDATING = "VALIDATING"
    DONE = "DONE"


class Task(BaseModel):
    id: str
    title: str
    raw_requirement: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    title: str
    raw_requirement: str
