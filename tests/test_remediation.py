from uuid import uuid4

from backend.events.models import Severity
from backend.remediation.engine import RemediationEngine
from backend.remediation.models import ActionStatus, ExecutionMode, RemediationRequest
from backend.remediation.tools import CheckDiskUtilizationTool, RestartServiceTool


def _request(action: str, arguments: dict[str, str] | None = None) -> RemediationRequest:
    return RemediationRequest(
        incident_id=uuid4(),
        action=action,
        arguments=arguments or {},
        incident_severity=Severity.WARNING,
    )


def test_observe_mode_never_executes() -> None:
    result = RemediationEngine([CheckDiskUtilizationTool()]).execute(
        _request("check_disk_utilization")
    )
    assert result.status == ActionStatus.SUGGESTED
    assert result.requires_approval is True


def test_unknown_action_is_rejected() -> None:
    result = RemediationEngine([]).execute(_request("run_arbitrary_shell"))
    assert result.status == ActionStatus.REJECTED


def test_restart_requires_authorization_and_approval() -> None:
    tool = RestartServiceTool({"edge-api.service"})
    engine = RemediationEngine([tool], mode=ExecutionMode.CONTROLLED_AUTO)
    invalid = engine.execute(_request("restart_authorized_service", {"service": "sshd.service"}), approved=True)
    assert invalid.status == ActionStatus.REJECTED
    pending = engine.execute(_request("restart_authorized_service", {"service": "edge-api.service"}))
    assert pending.status == ActionStatus.APPROVAL_REQUIRED


def test_argument_injection_is_rejected() -> None:
    result = RemediationEngine([CheckDiskUtilizationTool()], mode=ExecutionMode.CONTROLLED_AUTO).execute(
        _request("check_disk_utilization", {"path": "/; touch /tmp/pwned"})
    )
    assert result.status == ActionStatus.REJECTED
