from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.events.models import Event, Severity


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    REOPENED = "reopened"


class Incident(BaseModel):
    incident_id: UUID = Field(default_factory=uuid4)
    fingerprint: str
    host_id: str
    title: str
    severity: Severity
    status: IncidentStatus = IncidentStatus.OPEN
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_ids: list[UUID] = Field(default_factory=list)

    def add_event(self, event: Event) -> None:
        self.last_seen = event.timestamp
        if event.event_id not in self.event_ids:
            self.event_ids.append(event.event_id)
        if self.status == IncidentStatus.RESOLVED:
            self.status = IncidentStatus.REOPENED

    def acknowledge(self) -> None:
        if self.status in {IncidentStatus.OPEN, IncidentStatus.REOPENED}:
            self.status = IncidentStatus.ACKNOWLEDGED

    def resolve(self, verification_passed: bool = False) -> None:
        if not verification_passed:
            raise ValueError("Incident cannot be resolved without successful verification")
        if self.status not in {IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.REOPENED}:
            raise ValueError(f"Cannot resolve incident in state {self.status}")
        self.status = IncidentStatus.RESOLVED
