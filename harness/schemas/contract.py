from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ContractStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"


class FileSpec(BaseModel):
    path: str
    action: Literal["create", "modify", "delete"]
    description: str


class ContractSpec(BaseModel):
    """The structured implementation specification derived from approved decisions."""

    summary: str
    files: list[FileSpec]
    constraints: list[str]         # "must X" / "must not Y" rules
    acceptance_criteria: list[str]  # "when X, then Y" conditions


class Contract(BaseModel):
    id: str  # e.g. C001
    task_id: str
    scope: str                     # one-line summary of what this contract covers
    allowed_files: list[str]       # only these paths may appear in the patch
    forbidden: list[str]           # patterns that must not appear in added lines
    spec: ContractSpec
    status: ContractStatus = ContractStatus.DRAFT
    created_at: datetime
