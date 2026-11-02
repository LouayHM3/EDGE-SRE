# EDGE-SRE

Offline-first Linux infrastructure monitoring and incident response prototype.

## Current status

- **Phase 2:** typed monitoring collectors for CPU, memory, swap, disks, network, processes, uptime, and configured services.
- **Phase 3:** asyncio event bus, SQLite event persistence, deduplication, rule-based incident detection, and incident lifecycle management.
- **Phase 4:** deterministic, explainable diagnosis with validated structured output and no shell execution.
- **Phase 5:** optional local Ollama diagnosis with bounded concurrency, strict JSON validation, and deterministic fallback.
- **Phase 6:** secure remediation engine with execution modes, allowlisted tools, typed arguments, approval gates, timeouts, and audit logging.
- **Phase 7:** recovery verification, verification persistence, incident closure gating, and SRE recovery metrics.
- **Phase 8:** FastAPI REST/WebSocket API and React/TypeScript operational dashboard foundation.
- **Phase 9:** bounded dry-run incident simulators, isolated-container execution policy, and simulator safety tests.
- **Phase 10:** architecture/security/operations documentation and a safe event-bus benchmark.

The monitoring, event, and diagnostic layers do not require cloud services. Ollama is optional and accessed only through loopback.

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest
```

The collectors are designed for Linux. Platform-specific sources degrade explicitly through a `CollectionError` rather than silently fabricating observations.

## Local API container

The root [docker-compose.yml](docker-compose.yml)
exposes the API only on localhost and persists application data in a named
volume. Build and startup require the Python dependencies to be available to
Docker.

## Documentation

- [Architecture](docs/architecture.md)
- [Security model](docs/security-model.md)
- [Operations guide](docs/operations.md)

## Benchmark

Run `python scripts/benchmark_core.py` to measure local in-process event-bus
throughput. It publishes only synthetic in-memory events and does not touch
the host filesystem, network, services, or remediation tools.

## Simulation safety

Incident simulations default to dry-run. Resource pressure simulations require
an explicitly isolated container with bounded CPU, memory, disk, and runtime
limits. Service and network failure simulations cannot be executed by the host
runner and are delegated to the disposable container harness.
