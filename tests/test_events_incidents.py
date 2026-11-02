from datetime import datetime, timezone

from backend.events.models import EventType, Severity
from backend.incidents.detector import DetectionConfig, IncidentDetector, IncidentManager
from backend.monitoring.models import MetricSnapshot


def snapshot(**overrides) -> MetricSnapshot:
    values = dict(
        host_id="host-a", cpu_percent=95, memory_percent=20, memory_available_bytes=100,
        swap_percent=0, disks={"/": 20}, disk_read_bytes=0, disk_write_bytes=0,
        network={}, processes=[], uptime_seconds=10, services={},
        timestamp=datetime.now(timezone.utc),
    )
    values.update(overrides)
    return MetricSnapshot(**values)


def test_detector_emits_high_cpu_event() -> None:
    events = IncidentDetector(DetectionConfig(cpu_percent=90)).detect(snapshot())
    assert len(events) == 1
    assert events[0].event_type == EventType.METRIC_THRESHOLD
    assert events[0].severity == Severity.CRITICAL


def test_manager_deduplicates_by_fingerprint() -> None:
    manager = IncidentManager()
    first_events, first = manager.process(snapshot(cpu_percent=91))
    second_events, second = manager.process(snapshot(cpu_percent=92))
    assert len(first_events) == len(second_events) == 1
    assert first[0].incident_id == second[0].incident_id
    assert len(second[0].event_ids) == 2


def test_service_failure_creates_high_incident() -> None:
    events = IncidentDetector().detect(snapshot(cpu_percent=0, services={"sshd": "failed"}))
    assert events[0].severity == Severity.HIGH
    assert events[0].related_service == "sshd"

