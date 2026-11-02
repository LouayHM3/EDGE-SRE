from backend.api.state import ApplicationState
from backend.monitoring.models import MetricSnapshot


def test_state_records_snapshot_and_events() -> None:
    state = ApplicationState()
    events = state.record_snapshot(MetricSnapshot(
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
    assert events == []
    assert state.latest_snapshot is not None
