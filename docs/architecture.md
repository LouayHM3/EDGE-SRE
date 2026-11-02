# EDGE-SRE architecture

EDGE-SRE is an offline-first, modular SRE agent. The monitoring layer is
independent from diagnosis and remediation, so host observation continues when
Ollama or the dashboard is unavailable.

## Data flow

```text
psutil / procfs / systemd / journalctl
              |
       MonitoringScheduler
              |
       MetricSnapshot (Pydantic)
              |
        IncidentManager
        /             \
   EventBus         SQLite stores
      |                  |
  diagnostics       API state
      |                  |
  remediation ---- verification
              |
       FastAPI + WebSocket
              |
       React dashboard
```

## Trust boundaries

- Monitoring reads host state and emits typed snapshots.
- Diagnostics may use local Ollama, but receives structured evidence only.
- Remediation accepts only named tools and typed arguments.
- Critical or high-risk actions require approval.
- Verification, not the action result alone, determines incident closure.
- The dashboard is a local presentation layer and has no cloud telemetry path.

## Persistence

SQLite is the initial persistence layer. WAL mode is used for event storage;
event, remediation audit, and verification records are separated so retention
policies can evolve independently. NATS/MQTT can replace the in-process bus
behind the same publish/subscribe boundary.

## Resource policy

Monitoring uses bounded process collection and configurable intervals. Ollama
requests are grouped at incident level, constrained by a semaphore, and
validated before use. Simulation execution is isolated and opt-in.
