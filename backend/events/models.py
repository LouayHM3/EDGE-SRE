from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class EventType(StrEnum):
    METRIC_THRESHOLD = "metric_threshold"
    SERVICE_STATUS = "service_status"
    LOG_PATTERN = "log_pattern"
    NETWORK_ANOMALY = "network_anomaly"


class Event(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    host_id: str
    component: str
    severity: Severity
    event_type: EventType
    observed_value: float | str | dict[str, Any]
    threshold: float | str | None = None
    description: str
    related_service: str | None = None
    correlation_key: str | None = None

