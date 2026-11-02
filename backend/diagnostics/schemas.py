from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from backend.events.models import Severity


class Evidence(BaseModel):
    source: str
    observation: str


class RecommendedAction(BaseModel):
    action: str
    rationale: str
    risk: str = "low"


class Diagnosis(BaseModel):
    incident_id: UUID
    summary: str
    probable_root_causes: list[str] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_actions: list[RecommendedAction] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

