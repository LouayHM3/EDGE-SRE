from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.events.models import Severity


class ExecutionMode(StrEnum):
    OBSERVE = "observe"
    SUGGEST = "suggest"
    CONTROLLED_AUTO = "controlled_auto"


class ActionStatus(StrEnum):
    SUGGESTED = "suggested"
    APPROVAL_REQUIRED = "approval_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


class RemediationRequest(BaseModel):
    incident_id: UUID
    action: str
    arguments: dict[str, str] = Field(default_factory=dict)
    requested_by: str = "system"
    incident_severity: Severity = Severity.INFO


class RemediationResult(BaseModel):
    action_id: UUID = Field(default_factory=uuid4)
    request: RemediationRequest
    status: ActionStatus
    message: str
    output: str = ""
    requires_approval: bool = False

