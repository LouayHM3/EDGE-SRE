from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .models import Event, Severity

EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self, max_queue_size: int = 1000) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, Event]] = asyncio.PriorityQueue(maxsize=max_queue_size)
        self._handlers: list[EventHandler] = []
        self._sequence = 0
        self._stopped = False

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: Event) -> None:
        if self._stopped:
            raise RuntimeError("Event bus is stopped")
        self._sequence += 1
        priority = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.WARNING: 2,
            Severity.INFO: 3,
        }[event.severity]
        await self._queue.put((priority, self._sequence, event))

    async def run(self) -> None:
        while True:
            _, _, event = await self._queue.get()
            try:
                results = await asyncio.gather(
                    *(handler(event) for handler in self._handlers),
                    return_exceptions=True,
                )
                failures = [result for result in results if isinstance(result, Exception)]
                if failures:
                    raise RuntimeError(f"{len(failures)} event handler(s) failed")
            finally:
                self._queue.task_done()
            if self._stopped and self._queue.empty():
                return

    def stop(self) -> None:
        self._stopped = True
