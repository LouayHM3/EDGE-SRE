import asyncio

from backend.api.state import ApplicationState
from backend.monitoring.models import MetricSnapshot


def test_snapshot_publication_reaches_websocket_subscriber() -> None:
    async def scenario() -> None:
        state = ApplicationState()
        queue = state.subscribe()
        await state.record_snapshot_and_publish(MetricSnapshot(
            host_id="host-a",
            cpu_percent=1,
            memory_percent=1,
            memory_available_bytes=100,
            swap_percent=1,
            disks={"/": 1},
            disk_read_bytes=0,
            disk_write_bytes=0,
            network={},
            processes=[],
            uptime_seconds=10,
            services={},
        ))
        message = await queue.get()
        assert message["type"] == "snapshot"
        state.unsubscribe(queue)

    asyncio.run(scenario())
