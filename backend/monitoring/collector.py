from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterable
from typing import Any

import psutil

from .models import CollectionError, MetricSnapshot


class SystemCollector:
    """Collects host state without depending on the diagnostic or event layers."""

    def __init__(self, host_id: str | None = None, services: Iterable[str] = ()) -> None:
        self.host_id = host_id or socket.gethostname()
        self.services = tuple(services)

    def collect(self) -> MetricSnapshot:
        try:
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            disks = {
                mount: psutil.disk_usage(mount).percent
                for mount in self._mount_points()
            }
            io = psutil.disk_io_counters()
            network = {
                name: {
                    "bytes_sent": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "errin": stats.errin,
                    "errout": stats.errout,
                    "dropin": stats.dropin,
                    "dropout": stats.dropout,
                }
                for name, stats in psutil.net_io_counters(pernic=True).items()
            }
            return MetricSnapshot(
                host_id=self.host_id,
                cpu_percent=psutil.cpu_percent(interval=None),
                memory_percent=memory.percent,
                memory_available_bytes=memory.available,
                swap_percent=swap.percent,
                disks=disks,
                disk_read_bytes=io.read_bytes if io else 0,
                disk_write_bytes=io.write_bytes if io else 0,
                network=network,
                processes=self._processes(),
                uptime_seconds=self._uptime(),
                services=self._services(),
            )
        except (OSError, psutil.Error) as exc:
            raise CollectionError(f"Unable to collect host metrics: {exc}") from exc

    @staticmethod
    def _mount_points() -> list[str]:
        mounts: list[str] = []
        for partition in psutil.disk_partitions(all=False):
            if partition.mountpoint not in mounts:
                mounts.append(partition.mountpoint)
        if not mounts:
            mounts.append(os.path.abspath(os.sep))
        return mounts

    @staticmethod
    def _processes(limit: int = 50) -> list[dict[str, Any]]:
        processes: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "username", "memory_percent"]):
            try:
                processes.append(process.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return sorted(
            processes,
            key=lambda item: float(item.get("memory_percent") or 0),
            reverse=True,
        )[:limit]

    @staticmethod
    def _uptime() -> float:
        try:
            return max(0.0, time.time() - psutil.boot_time())
        except (OSError, psutil.Error) as exc:
            raise CollectionError(f"Unable to read system uptime: {exc}") from exc

    def _services(self) -> dict[str, str]:
        return {service: self._service_status(service) for service in self.services}

    @staticmethod
    def _service_status(service: str) -> str:
        try:
            result = subprocess.Popen(
                ["systemctl", "is-active", service],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            stdout, _ = result.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        status = stdout.strip()
        return status or "unknown"
