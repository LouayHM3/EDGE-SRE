from __future__ import annotations

from collections.abc import Callable, Iterable

from backend.incidents.models import Incident
from backend.remediation.models import ActionStatus, RemediationResult

from .models import VerificationCheck, VerificationResult, VerificationStatus

ServiceCheck = Callable[[str], tuple[bool, str]]


class RecoveryVerifier:
    def __init__(self, service_check: ServiceCheck | None = None) -> None:
        self.service_check = service_check or self._default_service_check

    def verify(
        self,
        incident: Incident,
        remediation: RemediationResult,
        *,
        snapshot=None,
        service: str | None = None,
        expected_statuses: Iterable[str] = ("active", "running"),
    ) -> VerificationResult:
        checks: list[VerificationCheck] = []
        checks.append(VerificationCheck(
            name="incident_match",
            passed=remediation.request.incident_id == incident.incident_id,
            detail="Remediation belongs to the incident being verified",
        ))
        action_succeeded = remediation.status == ActionStatus.SUCCEEDED
        checks.append(VerificationCheck(
            name="remediation_action",
            passed=action_succeeded,
            detail=remediation.message,
        ))

        if service is not None:
            healthy, detail = self.service_check(service)
            checks.append(VerificationCheck(
                name="service_health",
                passed=healthy,
                detail=detail,
            ))
            if snapshot is not None:
                status = snapshot.services.get(service)
                checks.append(VerificationCheck(
                    name="service_snapshot",
                    passed=status in set(expected_statuses),
                    detail=f"Observed service status: {status or 'missing'}",
                ))
        elif snapshot is not None:
            checks.append(VerificationCheck(
                name="metric_snapshot",
                passed=snapshot.host_id == incident.host_id,
                detail=f"Collected recovery snapshot from {snapshot.host_id}",
            ))
        else:
            checks.append(VerificationCheck(
                name="recovery_evidence",
                passed=False,
                detail="No service check or recovery snapshot was supplied",
            ))

        passed = all(check.passed for check in checks)
        return VerificationResult(
            incident_id=incident.incident_id,
            action_id=remediation.action_id,
            status=VerificationStatus.PASSED if passed else VerificationStatus.FAILED,
            checks=checks,
            snapshot=snapshot,
        )

    @staticmethod
    def _default_service_check(service: str) -> tuple[bool, str]:
        from backend.remediation.tools import CheckServiceHealthTool

        try:
            output = CheckServiceHealthTool().execute({"service": service}, 5.0).output
        except (OSError, RuntimeError, TimeoutError) as exc:
            return False, f"Service check failed: {exc}"
        return output in {"active", "running"}, f"Observed service status: {output}"
