from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class SimulationKind(StrEnum):
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    SERVICE_FAILURE = "service_failure"
    NETWORK = "network"
    REPEATED_SERVICE_FAILURE = "repeated_service_failure"


class SimulationRequest(BaseModel):
    kind: SimulationKind
    duration_seconds: int = Field(default=5, ge=1, le=30)
    size_megabytes: int = Field(default=16, ge=1, le=64)
    target_service: str | None = None
    workspace: Path | None = None


class SimulationResult(BaseModel):
    kind: SimulationKind
    executed: bool
    message: str
    cleanup_performed: bool = False

