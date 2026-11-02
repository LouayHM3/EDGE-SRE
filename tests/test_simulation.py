import pytest

from simulation.models import SimulationKind, SimulationRequest
from simulation.runner import SimulationRunner, SimulationSafetyError


def test_simulation_defaults_to_dry_run() -> None:
    result = SimulationRunner().run(
        SimulationRequest(kind=SimulationKind.CPU, duration_seconds=2)
    )
    assert result.executed is False
    assert "DRY RUN" in result.message


def test_execution_requires_isolated_container() -> None:
    with pytest.raises(SimulationSafetyError):
        SimulationRunner().run(
            SimulationRequest(kind=SimulationKind.CPU),
            dry_run=False,
        )


def test_bounds_are_validated() -> None:
    with pytest.raises(ValueError):
        SimulationRequest(kind=SimulationKind.DISK, size_megabytes=65)


def test_service_failure_is_not_host_executable() -> None:
    with pytest.raises(SimulationSafetyError):
        SimulationRunner(isolated_environment=True).run(
            SimulationRequest(kind=SimulationKind.SERVICE_FAILURE),
            dry_run=False,
        )
