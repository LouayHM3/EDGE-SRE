# Safe incident simulations

The simulator defaults to dry-run mode. It never runs resource pressure or
service/network failure actions unless both conditions are met:

1. The caller constructs `SimulationRunner(isolated_environment=True)`.
2. `EDGE_SRE_SIMULATION_ENV=container` is set inside the disposable container.

The Python runner limits duration to 30 seconds and memory/disk size to 64 MB.
Service and network failures are intentionally delegated to the container
harness rather than executed by the host runner.

Example dry run:

```bash
python -c "from simulation.runner import SimulationRunner; from simulation.models import SimulationRequest, SimulationKind; print(SimulationRunner().run(SimulationRequest(kind=SimulationKind.CPU)))"
```

