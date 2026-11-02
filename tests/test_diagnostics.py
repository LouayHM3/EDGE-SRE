from datetime import datetime, timezone

from backend.diagnostics.rules import RuleBasedDiagnosticEngine
from backend.events.models import Event, EventType, Severity
from backend.incidents.models import Incident


def test_cpu_diagnosis_is_structured_and_explainable() -> None:
    event = Event(
        host_id="host-a",
        component="cpu",
        severity=Severity.CRITICAL,
        event_type=EventType.METRIC_THRESHOLD,
        observed_value=97.0,
        threshold=90.0,
        description="cpu utilization is 97.0%",
        correlation_key="host-a:cpu",
        timestamp=datetime.now(timezone.utc),
    )
    incident = Incident(
        fingerprint="host-a:cpu",
        host_id="host-a",
        title=event.description,
        severity=event.severity,
        first_seen=event.timestamp,
        last_seen=event.timestamp,
        event_ids=[event.event_id],
    )

    diagnosis = RuleBasedDiagnosticEngine().diagnose(incident, [event])

    assert diagnosis.incident_id == incident.incident_id
    assert diagnosis.severity == Severity.CRITICAL
    assert diagnosis.evidence[0].observation == event.description
    assert "CPU saturation" in diagnosis.probable_root_causes[0]
    assert diagnosis.recommended_actions[0].action == "inspect_process_resource_consumption"


def test_service_diagnosis_recommends_logs_and_health_check() -> None:
    event = Event(
        host_id="host-a",
        component="service",
        severity=Severity.HIGH,
        event_type=EventType.SERVICE_STATUS,
        observed_value="failed",
        threshold="active",
        description="Service api is failed",
        related_service="api",
        correlation_key="host-a:service:api",
    )
    incident = Incident(
        fingerprint="host-a:service:api",
        host_id="host-a",
        title=event.description,
        severity=event.severity,
        event_ids=[event.event_id],
    )

    diagnosis = RuleBasedDiagnosticEngine().diagnose(incident, [event])
    actions = {action.action for action in diagnosis.recommended_actions}

    assert actions == {"inspect_service_logs", "check_service_health"}


def test_diagnosis_requires_evidence() -> None:
    incident = Incident(
        fingerprint="host-a:unknown",
        host_id="host-a",
        title="Unknown",
        severity=Severity.WARNING,
    )

    try:
        RuleBasedDiagnosticEngine().diagnose(incident, [])
    except ValueError as exc:
        assert "No evidence" in str(exc)
    else:
        raise AssertionError("diagnosis without evidence must fail")

