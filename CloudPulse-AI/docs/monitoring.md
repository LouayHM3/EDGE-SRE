# Model tracking, inference and monitoring

## Track an evaluated checkpoint

Run the dense autoencoder training first, then register the evaluated
checkpoint and its file hash. Tracking uses a local SQLite backend and
stores artifacts in `results/mlflow/artifacts`. Re-running registration
for the same checkpoint hash reuses the existing registry version.
The registered artifact is a PyTorch checkpoint for the CloudPulse
loader.

```powershell
.\.venv\Scripts\python.exe -m pip install -r monitoring/requirements-tracking.txt
.\.venv\Scripts\python.exe -m monitoring.track
```

## Start the inference API

```powershell
.\.venv\Scripts\python.exe -m pip install -r monitoring/requirements-api.txt
.\.venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/docs for the API schema. GET /model lists
the expected standardized feature columns and threshold. POST /predict
accepts an object with a features mapping. The API loads the checkpoint
on startup and returns its hash prefix as the version. GET /replay
returns the last verified simulated replay and its recent alert records.
GET /investigation takes run and scenario query parameters and
returns statistical service ranks. GET /metrics exposes Prometheus
metrics for API activity, latency, held-out ROC AUC, replay totals
and service investigation ranks.

## Start the monitoring stack

For portable Windows operation, extract Grafana 12.1.0 and Prometheus
3.5.0 from their official Windows AMD64 ZIPs into `.venv/tools`. After
generating the replay results, start the local stack:

```powershell
.\.venv\Scripts\python.exe -m monitoring.local_stack
```

The stack stays up until Ctrl+C. Add `--verify` to check the Prometheus
scrape and provisioned Grafana dashboard, save validation results, and
stop the processes. Grafana viewing in this mode is available only
through the loopback interface.

On a host with Docker Compose, run:

```powershell
docker compose up --build
```

The API, Prometheus and Grafana are bound to loopback ports 8000, 9090
and 3000. Grafana provisions the CloudPulse dashboard and its Prometheus
data source. Run API inference calls to populate the live inference-rate
and latency panels. The replay and service-ranking figures use artifacts
from the prior verified workflows. Mount the model and results folders
read-only in the API container.

If a trusted enterprise or antivirus proxy intercepts HTTPS, provide its
public CA certificate as a Compose build secret named `build_ca`. The
Dockerfile uses it only during package installation. Add a local Compose
override with `services.api.build.secrets: [build_ca]` and
`secrets.build_ca.file` pointing to the public PEM. Keep TLS verification
enabled and keep the local override outside version control.

[MLflow tracking](https://mlflow.org/docs/latest/ml/tracking) and
[Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
