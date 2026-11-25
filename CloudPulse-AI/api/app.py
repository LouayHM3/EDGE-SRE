"""Serve the dense checkpoint and summaries of the historical replay."""

from contextlib import asynccontextmanager, closing
from collections import Counter as Counts
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field
import torch

from src.deep_learning import build_autoencoder, score

REQUESTS = Counter("cloudpulse_predictions", "API-scored windows", ["alert"])
LATENCY = Histogram("cloudpulse_inference_seconds", "Dense model inference time")
REPLAY_WINDOWS = Gauge("cloudpulse_replay_windows", "Unique simulated windows persisted")
REPLAY_ALERTS = Gauge("cloudpulse_replay_alerts", "Alerts from the simulated replay")
REPLAY_LATENCY = Gauge("cloudpulse_replay_median_latency_seconds", "Median simulation publish-to-sink latency")
ROC_AUC = Gauge("cloudpulse_offline_roc_auc", "Held-out ROC AUC of the dense model")
TOP_RANK = Gauge("cloudpulse_investigation_top_rank", "Error scenarios with a top-ranked service deviation", ["service"])


@asynccontextmanager
async def lifespan(app):
    path = Path(os.getenv("CLOUDPULSE_MODEL", "models/dense_autoencoder.pt"))
    saved = torch.load(path, map_location="cpu", weights_only=True)
    features = saved["feature_columns"]
    model = build_autoencoder(len(features)).eval()
    model.load_state_dict(saved["state_dict"])
    app.state.model = model
    app.state.features = features
    app.state.threshold = saved["threshold"]
    app.state.version = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    model_metrics = Path("results/dense_autoencoder_metrics.json")
    if model_metrics.is_file():
        ROC_AUC.set(json.loads(model_metrics.read_text())["roc_auc"])
    ranks = Path("results/rca_rankings.csv")
    if ranks.is_file():
        with ranks.open(encoding="utf-8", newline="") as stream:
            counts = Counts(row["service"] for row in csv.DictReader(stream)
                            if row["rank"] == "1" and row["test"] != "correct")
        for service, count in counts.items():
            TOP_RANK.labels(service=service).set(count)
    yield


app = FastAPI(title="CloudPulse AI", lifespan=lifespan)


class Window(BaseModel):
    features: dict[str, Annotated[float, Field(allow_inf_nan=False)]]


def replay_context():
    summary_path = Path("results/streaming_summary.json")
    if not summary_path.is_file():
        return None
    summary = json.loads(summary_path.read_text())
    database = Path(summary["directory"].replace("\\", "/")) / "predictions.sqlite"
    return summary, database


@app.get("/health")
def health():
    return {"status": "ready", "model_version": app.state.version}


@app.get("/model")
def model_info():
    return {"version": app.state.version, "feature_columns": app.state.features,
            "threshold": app.state.threshold, "input": "standardized LO2v2 window features"}


@app.post("/predict")
def predict(window: Window):
    if set(window.features) != set(app.state.features):
        raise HTTPException(status_code=422, detail="Supply all model features named by GET /model")
    values = torch.tensor([[window.features[key] for key in app.state.features]], dtype=torch.float32)
    if not values.isfinite().all():
        raise HTTPException(status_code=422, detail="Feature values exceed float32 range")
    with LATENCY.time():
        deviation = score(app.state.model, values).item()
    if not math.isfinite(deviation):
        raise HTTPException(status_code=422, detail="Feature values produce a non-finite score")
    alert = deviation >= app.state.threshold
    REQUESTS.labels(alert=str(alert).lower()).inc()
    return {"score": deviation, "alert": alert, "model_version": app.state.version}


@app.get("/replay")
def replay(limit: Annotated[int, Query(ge=1, le=200)] = 20):
    context = replay_context()
    if context is None:
        raise HTTPException(status_code=404, detail="Run the historical replay first")
    summary, database = context
    if not database.is_file():
        raise HTTPException(status_code=404, detail="Replay database is unavailable")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        alerts = [dict(row) for row in db.execute(
            "SELECT run, test, window_start, score FROM predictions WHERE alert = 1 "
            "ORDER BY window_start DESC LIMIT ?", (limit,),
        )]
    return {"summary": summary, "alerts": alerts}


@app.get("/investigation")
def investigation(run: str = Query(max_length=100), scenario: str = Query(max_length=100)):
    path = Path("results/rca_rankings.csv")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Run the service investigation first")
    with path.open(encoding="utf-8", newline="") as stream:
        ranks = [
            {"service": row["service"], "rank": int(row["rank"]),
             "fraction_above_reference": float(row["fraction_above_reference"])
             if row["fraction_above_reference"] else None}
            for row in csv.DictReader(stream) if row["run"] == run and row["test"] == scenario
        ]
    return {"kind": "statistical service deviations", "services": ranks}


@app.get("/metrics", include_in_schema=False)
def metrics():
    context = replay_context()
    if context:
        summary, _ = context
        REPLAY_WINDOWS.set(summary["unique_predictions"])
        REPLAY_ALERTS.set(summary["alerts"])
        REPLAY_LATENCY.set(summary["median_publish_to_sink_ms"] / 1000)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
