from __future__ import annotations

import asyncio
import json
import sys
import statistics
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.events.bus import EventBus
from backend.events.models import Event, EventType, Severity


async def benchmark_event_bus(count: int) -> dict[str, float | int]:
    bus = EventBus(max_queue_size=count)
    processed = 0

    async def consume(event: Event) -> None:
        nonlocal processed
        processed += 1

    bus.subscribe(consume)
    worker = asyncio.create_task(bus.run())
    started = time.perf_counter()
    for _ in range(count):
        await bus.publish(Event(
            host_id="benchmark",
            component="synthetic",
            severity=Severity.INFO,
            event_type=EventType.METRIC_THRESHOLD,
            observed_value=1,
            threshold=0,
            description="benchmark event",
            event_id=uuid4(),
        ))
    await bus._queue.join()
    elapsed = time.perf_counter() - started
    bus.stop()
    await worker
    return {
        "events": count,
        "processed": processed,
        "elapsed_seconds": round(elapsed, 6),
        "events_per_second": round(count / elapsed if elapsed else 0, 2),
    }


def main() -> None:
    samples = [asyncio.run(benchmark_event_bus(1000)) for _ in range(3)]
    print(json.dumps({
        "samples": samples,
        "median_events_per_second": round(
            statistics.median(sample["events_per_second"] for sample in samples), 2
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
