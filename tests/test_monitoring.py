from backend.monitoring.collector import SystemCollector
from backend.monitoring.models import MetricSnapshot


def test_snapshot_is_typed() -> None:
    snapshot = SystemCollector(host_id="test-host").collect()
    assert isinstance(snapshot, MetricSnapshot)
    assert snapshot.host_id == "test-host"
    assert snapshot.uptime_seconds >= 0
    assert snapshot.memory_percent >= 0

