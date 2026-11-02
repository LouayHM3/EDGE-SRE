from uuid import uuid4

from backend.events.models import Severity
from backend.incidents.models import Incident
from backend.remediation.models import ActionStatus, RemediationRequest, RemediationResult
from backend.verification.engine import RecoveryVerifier
from backend.verification.metrics import availability, remediation_success_rate
from backend.verification.models import VerificationStatus


def _incident() -> Incident:
    return Incident(
        incident_id=uuid4(),
        fingerprint="host-a:service:api",
        host_id="host-a",
        title="Service api failed",
        severity=Severity.HIGH,
    )


def _remediation(incident: Incident, status: ActionStatus) -> RemediationResult:
    return RemediationResult(
        request=RemediationRequest(
            incident_id=incident.incident_id,
            action="restart_authorized_service",
        ),
        status=status,
        message=status.value,
    )


def test_failed_remediation_cannot_verify_recovery() -> None:
    incident = _incident()
    result = RecoveryVerifier(service_check=lambda service: (True, "active")).verify(
        incident, _remediation(incident, ActionStatus.FAILED), service="api.service"
    )
    assert result.status == VerificationStatus.FAILED


def test_successful_service_check_verifies_recovery() -> None:
    incident = _incident()
    result = RecoveryVerifier(service_check=lambda service: (True, "active")).verify(
        incident, _remediation(incident, ActionStatus.SUCCEEDED), service="api.service"
    )
    assert result.status == VerificationStatus.PASSED


def test_incident_resolution_requires_verification() -> None:
    incident = _incident()
    try:
        incident.resolve()
    except ValueError as exc:
        assert "verification" in str(exc)
    else:
        raise AssertionError("unverified incident must not resolve")
    incident.resolve(verification_passed=True)
    assert incident.status.value == "resolved"


def test_sre_metrics_are_bounded() -> None:
    assert availability(9, 10) == 0.9
    incident = _incident()
    assert remediation_success_rate([_remediation(incident, ActionStatus.SUCCEEDED)]) == 1.0
