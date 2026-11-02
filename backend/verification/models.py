from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.monitoring.models import MetricSnapshot


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class VerificationResult(BaseModel):
    verification_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    action_id: UUID | None = None
    status: VerificationStatus
    checks: list[VerificationCheck] = Field(min_length=1)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    snapshot: MetricSnapshot | None = None

