from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .collector import SystemCollector
from .models import MetricSnapshot

SnapshotHandler = Callable[[MetricSnapshot], Awaitable[None]]


class MonitoringScheduler:
    """Runs collection independently from event processing and diagnostics."""

    def __init__(
        self,
        collector: SystemCollector,
        handler: SnapshotHandler,
        interval_seconds: float = 15.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.collector = collector
        self.handler = handler
        self.interval_seconds = interval_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            snapshot = await asyncio.to_thread(self.collector.collect)
            await self.handler(snapshot)
            try:
                await asyncio.wait_for(self._stop.wait(), self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()
