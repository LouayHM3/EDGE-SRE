from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Iterable

from backend.remediation.models import ActionStatus, RemediationResult


def mean_time_to_detect(
    detected_at: Iterable[datetime], observed_at: Iterable[datetime]
) -> float | None:
    durations = [
        (detected - observed).total_seconds()
        for detected, observed in zip(detected_at, observed_at)
        if detected >= observed
    ]
    return mean(durations) if durations else None


def mean_time_to_recover(
    recovered_at: Iterable[datetime], opened_at: Iterable[datetime]
) -> float | None:
    durations = [
        (recovered - opened).total_seconds()
        for recovered, opened in zip(recovered_at, opened_at)
        if recovered >= opened
    ]
    return mean(durations) if durations else None


def availability(successful_checks: int, total_checks: int) -> float:
    if total_checks < 0 or successful_checks < 0 or successful_checks > total_checks:
        raise ValueError("check counts must be non-negative and successful <= total")
    return 1.0 if total_checks == 0 else successful_checks / total_checks


def remediation_success_rate(results: Iterable[RemediationResult]) -> float:
    values = list(results)
    if not values:
        return 1.0
    successful = sum(result.status == ActionStatus.SUCCEEDED for result in values)
    return successful / len(values)

