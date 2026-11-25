"""Build run-disjoint sliding-window datasets from the LO2v2 metrics cache."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from src.download import RAW, SERVICES
from src.evaluate import COUNTERS, GAUGES

WINDOW = 20
STRIDE = 10
SEED = 42
OUTPUT = Path("data/processed")
KEYS = ["run", "test", "timestamp"]
SIGNALS = GAUGES + COUNTERS


def read_service(path):
    frame = pd.read_csv(path, usecols=[*KEYS, "container", *SIGNALS])
    service = path.name.partition("-light-oauth2-oauth2-")[2].removesuffix("-1-metrics.csv")
    if service not in SERVICES or not frame.container.eq(f"light-oauth2-oauth2-{service}-1").all():
        raise ValueError(f"Unexpected container in {path}")
    frame["timestamp"] = pd.to_datetime(frame.timestamp, unit="s", utc=True, errors="coerce")
    frame = frame.dropna(subset=KEYS).drop_duplicates()
    if frame.duplicated(KEYS).any():
        raise ValueError(f"Conflicting observation keys in {path}")
    frame = frame.sort_values(KEYS).set_index(KEYS)
    frame = frame[SIGNALS].replace([np.inf, -np.inf], np.nan).astype(float)
    rates = frame[COUNTERS].groupby(level=["run", "test"]).diff()
    elapsed = frame.index.to_frame()["timestamp"].groupby(level=["run", "test"]).diff().dt.total_seconds()
    rates = rates.div(elapsed.where(elapsed.eq(1)), axis=0)
    frame[COUNTERS] = rates.where(rates.ge(0))
    return frame.add_prefix(f"{service}__")


def load_aligned(paths=None):
    paths = sorted(RAW.glob("*.csv")) if paths is None else list(paths)
    if not paths:
        raise ValueError(f"No metrics CSVs in {RAW}")
    frames = {service: [] for service in SERVICES}
    for path in paths:
        frame = read_service(path)
        service = frame.columns[0].split("__", maxsplit=1)[0]
        frames[service].append(frame)
    if missing := [service for service, items in frames.items() if not items]:
        raise ValueError(f"Missing services: {missing}")
    aligned = pd.concat(
        [pd.concat(frames[service], verify_integrity=True) for service in SERVICES],
        axis=1, join="outer",
    ).sort_index()
    return aligned


def make_windows(aligned):
    times = ["window_start", "window_end"]
    columns = [f"{signal}__{stat}" for signal in aligned for stat in ("mean", "std")]
    blocks = []
    for (run, test), group in aligned.groupby(level=["run", "test"], sort=False):
        series = group.droplevel(["run", "test"])
        grid = pd.date_range(series.index.min(), series.index.max(), freq="s")
        values = series.reindex(grid).to_numpy()
        if len(values) < WINDOW:
            continue
        windows = np.lib.stride_tricks.sliding_window_view(values, WINDOW, axis=0)[::STRIDE]
        valid = np.isfinite(windows).all(axis=(1, 2))
        starts = np.arange(0, len(values) - WINDOW + 1, STRIDE)[valid]
        windows = windows[valid]
        features = np.stack((windows.mean(axis=2), windows.std(axis=2)), axis=-1)
        block = pd.DataFrame(features.reshape(len(starts), len(columns)), columns=columns)
        block[times[0]], block[times[1]] = grid[starts], grid[starts + WINDOW - 1]
        block["run"], block["test"], block["error"] = run, test, test != "correct"
        blocks.append(block)
    if not blocks:
        raise ValueError("No candidate windows found")
    return pd.concat(blocks, ignore_index=True), columns


def preprocess():
    aligned = load_aligned()
    windows, columns = make_windows(aligned)
    runs = sorted(windows.run.unique())
    train, held_out = train_test_split(runs, test_size=0.4, random_state=SEED)
    validation, test = train_test_split(held_out, test_size=0.5, random_state=SEED)
    splits = {"train": sorted(train), "validation": sorted(validation), "test": sorted(test)}
    mapping = {run: split for split, members in splits.items() for run in members}
    windows["split"] = windows.run.map(mapping)
    scaler = StandardScaler().fit(windows.loc[windows.split.eq("train"), columns])
    windows[columns] = scaler.transform(windows[columns])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    aligned.reset_index().to_parquet(OUTPUT / "aligned_metrics.parquet", index=False)
    for split in splits:
        windows[windows.split.eq(split)].to_parquet(OUTPUT / f"windows_{split}.parquet", index=False)
    metadata = {
        "window_seconds": WINDOW, "stride_seconds": STRIDE, "seed": SEED,
        "runs": splits, "feature_columns": columns,
        "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
        "aligned_rows": len(aligned),
        "aligned_incomplete_rows": int(aligned.isna().any(axis=1).sum()),
    }
    (OUTPUT / "preprocessing.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(windows.groupby(["split", "error"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    preprocess()
