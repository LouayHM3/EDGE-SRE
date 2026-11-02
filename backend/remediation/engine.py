from __future__ import annotations

from collections.abc import Iterable

from .audit import AuditLog
from .models import ActionStatus, ExecutionMode, RemediationRequest, RemediationResult
from .policies import AuthorizationPolicy
from .tools import RemediationTool, ToolExecutionError, ToolValidationError


class RemediationEngine:
    def __init__(
        self,
        tools: Iterable[RemediationTool],
        mode: ExecutionMode = ExecutionMode.OBSERVE,
        timeout_seconds: float = 10.0,
        audit_log: AuditLog | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.tools = {tool.name: tool for tool in tools}
        self.policy = AuthorizationPolicy(mode)
        self.timeout_seconds = timeout_seconds
        self.audit_log = audit_log

    def execute(self, request: RemediationRequest, approved: bool = False) -> RemediationResult:
        tool = self.tools.get(request.action)
        if tool is None:
            return self._record(RemediationResult(
                request=request,
                status=ActionStatus.REJECTED,
                message="Action is not allowlisted",
            ))
        try:
            tool.validate(request.arguments)
        except ToolValidationError as exc:
            return self._record(RemediationResult(
                request=request, status=ActionStatus.REJECTED, message=str(exc),
            ))

        if self.policy.mode == ExecutionMode.OBSERVE:
            return self._record(RemediationResult(
                request=request,
                status=ActionStatus.SUGGESTED,
                message="OBSERVE mode does not execute remediation actions",
                requires_approval=True,
            ))
        if self.policy.mode == ExecutionMode.SUGGEST or self.policy.requires_approval(request, tool):
            if not approved:
                return self._record(RemediationResult(
                    request=request,
                    status=ActionStatus.APPROVAL_REQUIRED,
                    message="Explicit approval is required for this action",
                    requires_approval=True,
                ))
        try:
            result = tool.execute(request.arguments, self.timeout_seconds)
        except TimeoutError as exc:
            return self._record(RemediationResult(
                request=request, status=ActionStatus.TIMED_OUT, message=str(exc),
            ))
        except (ToolExecutionError, OSError) as exc:
            return self._record(RemediationResult(
                request=request, status=ActionStatus.FAILED, message=str(exc),
            ))
        return self._record(RemediationResult(
            request=request,
            status=ActionStatus.SUCCEEDED,
            message="Allowlisted remediation completed",
            output=result.output,
        ))

    def _record(self, result: RemediationResult) -> RemediationResult:
        if self.audit_log is not None:
            self.audit_log.record(result)
        return result

