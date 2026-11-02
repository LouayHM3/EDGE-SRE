from __future__ import annotations

from collections.abc import Sequence

from backend.events.models import Event, EventType, Severity
from backend.incidents.models import Incident

from .schemas import Diagnosis, Evidence, RecommendedAction


class RuleBasedDiagnosticEngine:
    """Produces explainable diagnoses without external services or shell access."""

    def diagnose(self, incident: Incident, events: Sequence[Event]) -> Diagnosis:
        related = [event for event in events if event.event_id in incident.event_ids]
        if not related:
            raise ValueError(f"No evidence found for incident {incident.incident_id}")

        evidence = [
            Evidence(source=event.component, observation=event.description)
            for event in related
        ]
        causes: list[str] = []
        actions: list[RecommendedAction] = []
        highest_severity = max((event.severity for event in related), key=self._severity_rank)

        metric_events = [
            event for event in related if event.event_type == EventType.METRIC_THRESHOLD
        ]
        for event in metric_events:
            if event.component == "cpu":
                causes.append("Sustained CPU saturation or a CPU-intensive workload")
                actions.append(RecommendedAction(
                    action="inspect_process_resource_consumption",
                    rationale="Identify the process responsible for CPU pressure before taking action.",
                ))
            elif event.component == "memory":
                causes.append("Memory pressure caused by workload growth or insufficient available memory")
                actions.append(RecommendedAction(
                    action="inspect_process_resource_consumption",
                    rationale="Identify memory-consuming processes and reclaimable workload.",
                ))
            elif event.component == "swap":
                causes.append("Swap pressure indicating insufficient available physical memory")
                actions.append(RecommendedAction(
                    action="inspect_process_resource_consumption",
                    rationale="Correlate swap growth with memory-consuming processes.",
                ))
            elif event.component.startswith("disk:"):
                causes.append("Filesystem capacity exhaustion or abnormal disk consumption")
                actions.append(RecommendedAction(
                    action="check_disk_utilization",
                    rationale="Locate the full filesystem and quantify remaining capacity.",
                ))

        service_events = [
            event for event in related if event.event_type == EventType.SERVICE_STATUS
        ]
        for event in service_events:
            service = event.related_service or "the affected service"
            causes.append(f"{service} is not reporting an active systemd state")
            actions.extend([
                RecommendedAction(
                    action="inspect_service_logs",
                    rationale=f"Review recent logs for {service} to identify startup or runtime errors.",
                ),
                RecommendedAction(
                    action="check_service_health",
                    rationale=f"Confirm whether {service} recovers and responds to its health check.",
                ),
            ])

        if not causes:
            causes.append("The incident condition is not covered by the deterministic rules")

        return Diagnosis(
            incident_id=incident.incident_id,
            summary=self._summary(incident, causes),
            probable_root_causes=list(dict.fromkeys(causes)),
            evidence=evidence,
            severity=highest_severity,
            confidence=self._confidence(related, causes),
            recommended_actions=self._unique_actions(actions),
            limitations=[
                "Diagnosis is based only on collected structured events.",
                "No logs or process history were supplied to the rule engine.",
            ],
        )

    @staticmethod
    def _severity_rank(severity: Severity) -> int:
        return {
            Severity.INFO: 0,
            Severity.WARNING: 1,
            Severity.HIGH: 2,
            Severity.CRITICAL: 3,
        }[severity]

    @staticmethod
    def _summary(incident: Incident, causes: list[str]) -> str:
        return f"{incident.title}. Most likely cause: {causes[0]}."

    @staticmethod
    def _confidence(events: Sequence[Event], causes: list[str]) -> float:
        if not events:
            return 0.0
        return min(0.95, 0.55 + (0.15 if len(events) > 1 else 0.0) + (0.1 if causes else 0.0))

    @staticmethod
    def _unique_actions(actions: list[RecommendedAction]) -> list[RecommendedAction]:
        unique: dict[str, RecommendedAction] = {}
        for action in actions:
            unique.setdefault(action.action, action)
        return list(unique.values())

