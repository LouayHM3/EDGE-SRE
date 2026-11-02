import asyncio
import json
from uuid import uuid4

from backend.diagnostics.ollama import (
    FallbackDiagnosticProvider,
    OllamaDiagnosticProvider,
    OllamaUnavailable,
)
from backend.diagnostics.rules import RuleBasedDiagnosticEngine
from backend.events.models import Event, EventType, Severity
from backend.incidents.models import Incident


def _incident_and_event() -> tuple[Incident, Event]:
    event = Event(
        host_id="host-a",
        component="cpu",
        severity=Severity.HIGH,
        event_type=EventType.METRIC_THRESHOLD,
        observed_value=91.0,
        threshold=90.0,
        description="cpu utilization is 91.0%",
    )
    incident = Incident(
        incident_id=uuid4(),
        fingerprint="host-a:cpu",
        host_id="host-a",
        title=event.description,
        severity=event.severity,
        event_ids=[event.event_id],
    )
    return incident, event


def test_ollama_provider_validates_structured_output() -> None:
    incident, event = _incident_and_event()
    output = {
        "incident_id": str(incident.incident_id),
        "summary": "CPU pressure detected.",
        "probable_root_causes": ["CPU-intensive workload"],
        "evidence": [{"source": "cpu", "observation": event.description}],
        "severity": "high",
        "confidence": 0.8,
        "recommended_actions": [],
        "limitations": [],
    }

    def transport(payload: bytes, timeout: float) -> bytes:
        request = json.loads(payload)
        assert request["format"] == "json"
        assert request["stream"] is False
        return json.dumps({"response": json.dumps(output)}).encode()

    diagnosis = asyncio.run(
        OllamaDiagnosticProvider(transport=transport).diagnose(incident, [event])
    )
    assert diagnosis.incident_id == incident.incident_id
    assert diagnosis.confidence == 0.8


def test_fallback_is_used_when_ollama_is_unavailable() -> None:
    incident, event = _incident_and_event()

    def unavailable(payload: bytes, timeout: float) -> bytes:
        raise OSError("connection refused")

    diagnosis = asyncio.run(
        FallbackDiagnosticProvider(
            OllamaDiagnosticProvider(transport=unavailable),
            RuleBasedDiagnosticEngine(),
        ).diagnose(incident, [event])
    )
    assert "deterministic fallback" in diagnosis.limitations[-1]


def test_invalid_ollama_output_is_rejected() -> None:
    incident, event = _incident_and_event()

    def invalid(payload: bytes, timeout: float) -> bytes:
        return json.dumps({"response": '{"severity":"invalid"}'}).encode()

    try:
        asyncio.run(OllamaDiagnosticProvider(transport=invalid).diagnose(incident, [event]))
    except OllamaUnavailable:
        pass
    else:
        raise AssertionError("invalid Ollama output must be rejected")
