from __future__ import annotations

from collections.abc import Iterable

from backend.events.models import Event, EventType, Severity
from backend.monitoring.models import MetricSnapshot

from .models import Incident


class DetectionConfig:
    def __init__(
        self,
        cpu_percent: float = 90.0,
        memory_percent: float = 90.0,
        swap_percent: float = 80.0,
        disk_percent: float = 90.0,
    ) -> None:
        self.cpu_percent = cpu_percent
        self.memory_percent = memory_percent
        self.swap_percent = swap_percent
        self.disk_percent = disk_percent


class IncidentDetector:
    def __init__(self, config: DetectionConfig | None = None) -> None:
        self.config = config or DetectionConfig()

    def detect(self, snapshot: MetricSnapshot) -> list[Event]:
        events: list[Event] = []
        if snapshot.cpu_percent >= self.config.cpu_percent:
            events.append(self._threshold_event(snapshot, "cpu", snapshot.cpu_percent, self.config.cpu_percent))
        if snapshot.memory_percent >= self.config.memory_percent:
            events.append(self._threshold_event(snapshot, "memory", snapshot.memory_percent, self.config.memory_percent))
        if snapshot.swap_percent >= self.config.swap_percent:
            events.append(self._threshold_event(snapshot, "swap", snapshot.swap_percent, self.config.swap_percent))
        for mount, usage in snapshot.disks.items():
            if usage >= self.config.disk_percent:
                events.append(self._threshold_event(snapshot, f"disk:{mount}", usage, self.config.disk_percent))
        for service, status in snapshot.services.items():
            if status not in {"active", "running"}:
                events.append(Event(
                    host_id=snapshot.host_id, component="service", severity=Severity.HIGH,
                    event_type=EventType.SERVICE_STATUS, observed_value=status,
                    threshold="active", description=f"Service {service} is {status}",
                    related_service=service, correlation_key=f"{snapshot.host_id}:service:{service}",
                ))
        return events

    @staticmethod
    def _threshold_event(snapshot: MetricSnapshot, component: str, observed: float, threshold: float) -> Event:
        severity = Severity.CRITICAL if observed >= threshold + 5 else Severity.WARNING
        return Event(
            host_id=snapshot.host_id, component=component, severity=severity,
            event_type=EventType.METRIC_THRESHOLD, observed_value=observed,
            threshold=threshold, description=f"{component} utilization is {observed:.1f}%",
            correlation_key=f"{snapshot.host_id}:{component}",
        )


class IncidentManager:
    def __init__(self, detector: IncidentDetector | None = None) -> None:
        self.detector = detector or IncidentDetector()
        self.incidents: dict[str, Incident] = {}

    def process(self, snapshot: MetricSnapshot) -> tuple[list[Event], list[Incident]]:
        events = self.detector.detect(snapshot)
        changed: list[Incident] = []
        for event in events:
            fingerprint = event.correlation_key or f"{event.host_id}:{event.component}:{event.event_type}"
            incident = self.incidents.get(fingerprint)
            if incident is None:
                incident = Incident(
                    fingerprint=fingerprint,
                    host_id=event.host_id,
                    title=event.description,
                    severity=event.severity,
                    first_seen=event.timestamp,
                    last_seen=event.timestamp,
                )
                self.incidents[fingerprint] = incident
            incident.add_event(event)
            changed.append(incident)
        return events, changed

    def active(self) -> Iterable[Incident]:
        return (incident for incident in self.incidents.values() if incident.status != "resolved")

