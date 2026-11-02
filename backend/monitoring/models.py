from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MetricSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    host_id: str
    cpu_percent: float
    memory_percent: float
    memory_available_bytes: int
    swap_percent: float
    disks: dict[str, float]
    disk_read_bytes: int
    disk_write_bytes: int
    network: dict[str, dict[str, int]]
    processes: list[dict[str, Any]]
    uptime_seconds: float
    services: dict[str, str]


class CollectionError(RuntimeError):
    """Raised when a required monitoring source cannot be collected."""

