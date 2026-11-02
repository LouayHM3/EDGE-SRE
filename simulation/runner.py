from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import SimulationKind, SimulationRequest, SimulationResult


class SimulationSafetyError(RuntimeError):
    """Raised when a simulation is not explicitly authorized for an isolated environment."""


class SimulationRunner:
    """Plans bounded simulations; execution requires an explicitly marked container."""

    def __init__(self, *, isolated_environment: bool = False) -> None:
        self.isolated_environment = isolated_environment

    def run(self, request: SimulationRequest, *, dry_run: bool = True) -> SimulationResult:
        if dry_run:
            return SimulationResult(
                kind=request.kind,
                executed=False,
                message=self.describe(request),
            )
        if not self.isolated_environment or os.environ.get("EDGE_SRE_SIMULATION_ENV") != "container":
            raise SimulationSafetyError(
                "Simulation execution requires an isolated container and "
                "EDGE_SRE_SIMULATION_ENV=container"
            )
        if request.kind in {SimulationKind.SERVICE_FAILURE, SimulationKind.REPEATED_SERVICE_FAILURE}:
            raise SimulationSafetyError(
                "Service failure simulations must be driven by the disposable test container"
            )
        if request.kind == SimulationKind.NETWORK:
            raise SimulationSafetyError(
                "Network simulation is only available through the container network profile"
            )
        if request.kind == SimulationKind.DISK:
            return self._bounded_disk(request)
        command = self._command(request)
        try:
            subprocess.run(
                command,
                check=True,
                timeout=request.duration_seconds + 5,
                shell=False,
                cwd=str(request.workspace) if request.workspace else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Simulation exceeded its timeout") from exc
        return SimulationResult(
            kind=request.kind,
            executed=True,
            message="Bounded simulation completed",
            cleanup_performed=True,
        )

    @staticmethod
    def describe(request: SimulationRequest) -> str:
        return (
            f"DRY RUN: {request.kind.value} simulation for "
            f"{request.duration_seconds}s, capped at {request.size_megabytes}MB"
        )

    @staticmethod
    def _command(request: SimulationRequest) -> list[str]:
        if request.kind == SimulationKind.CPU:
            code = (
                "import time; end=time.monotonic()+int(__import__('sys').argv[1]); "
                "x=0\nwhile time.monotonic()<end: x=(x+1)%1000003"
            )
        else:
            code = (
                "import time; data=bytearray(int(__import__('sys').argv[2])*1024*1024); "
                "time.sleep(int(__import__('sys').argv[1])); del data"
            )
        return [sys.executable, "-c", code, str(request.duration_seconds), str(request.size_megabytes)]

    @staticmethod
    def _bounded_disk(request: SimulationRequest) -> SimulationResult:
        workspace = request.workspace or Path(tempfile.mkdtemp(prefix="edge-sre-sim-"))
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "bounded-pressure.bin"
        try:
            with target.open("wb") as handle:
                handle.write(b"\0" * request.size_megabytes * 1024 * 1024)
            return SimulationResult(
                kind=request.kind,
                executed=True,
                message=f"Created bounded temporary file at {target}",
                cleanup_performed=True,
            )
        finally:
            target.unlink(missing_ok=True)

