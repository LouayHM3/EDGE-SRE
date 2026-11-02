from __future__ import annotations

from backend.events.models import Severity

from .models import ExecutionMode, RemediationRequest
from .tools import RemediationTool


class AuthorizationPolicy:
    def __init__(self, mode: ExecutionMode = ExecutionMode.OBSERVE) -> None:
        self.mode = mode

    def requires_approval(self, request: RemediationRequest, tool: RemediationTool) -> bool:
        if self.mode != ExecutionMode.CONTROLLED_AUTO:
            return True
        return (
            not tool.auto_allowed
            or request.incident_severity in {Severity.HIGH, Severity.CRITICAL}
        )

