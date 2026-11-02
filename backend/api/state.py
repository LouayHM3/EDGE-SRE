from __future__ import annotations

import asyncio
from backend.events.models import Event
from backend.incidents.detector import IncidentManager
from backend.monitoring.models import MetricSnapshot


class ApplicationState:
    def __init__(self) -> None:
        self.incidents = IncidentManager()
        self.latest_snapshot: MetricSnapshot | None = None
        self.events: list[Event] = []
        self._subscribers: set[asyncio.Queue[dict]] = set()

    def record_snapshot(self, snapshot: MetricSnapshot) -> list[Event]:
        self.latest_snapshot = snapshot
        events, _ = self.incidents.process(snapshot)
        self.events.extend(events)
        return events

    async def record_snapshot_and_publish(self, snapshot: MetricSnapshot) -> list[Event]:
        events = self.record_snapshot(snapshot)
        await self.publish({
            "type": "snapshot",
            "snapshot": snapshot.model_dump(mode="json"),
        })
        for event in events:
            await self.publish({
                "type": "event",
                "event": event.model_dump(mode="json"),
            })
        return events

    async def publish(self, message: dict) -> None:
        for subscriber in tuple(self._subscribers):
            try:
                subscriber.put_nowait(message)
            except asyncio.QueueFull:
                self._subscribers.discard(subscriber)

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)
