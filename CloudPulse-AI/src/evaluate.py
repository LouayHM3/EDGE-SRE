import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score, balanced_accuracy_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import RobustScaler

from src.download import RAW, SERVICES

KEYS = ["run", "test"]
GAUGES = ["container_memory_rss", "container_memory_working_set_bytes"]
COUNTERS = [
    "container_cpu_usage_seconds_total", "container_fs_reads_bytes_total",
    "container_fs_writes_bytes_total", "container_network_receive_bytes_total",
    "container_network_transmit_bytes_total",
]
SIGNALS = GAUGES + COUNTERS
WINDOW = 20


def summarize(path):
    data = pd.read_csv(path, usecols=["timestamp", *KEYS, *SIGNALS])
    service = path.name.partition("-light-oauth2-oauth2-")[2].removesuffix("-1-metrics.csv")
    rows = []
    for (run, scenario), group in data.groupby(KEYS):
        window = group.sort_values("timestamp").drop_duplicates("timestamp").iloc[:WINDOW]
        if len(window) != WINDOW:
            continue
        features = window[GAUGES].median().to_dict()
        elapsed = window.timestamp.diff()
        rates = window[COUNTERS].diff().div(elapsed, axis=0)
        features.update(rates.where(rates >= 0).median().to_dict())
        rows.append({"run": run, "test": scenario, "service": service, **features})
    return pd.DataFrame(rows, columns=[*KEYS, "service", *SIGNALS])


def collect(paths, workers):
    if workers == 1:
        return pd.concat(map(summarize, paths), ignore_index=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return pd.concat(pool.map(summarize, paths), ignore_index=True)


def evaluate(table):
    features = table.pivot(index=KEYS, columns="service", values=SIGNALS)
    features = features.reindex(columns=pd.MultiIndex.from_product([SIGNALS, SERVICES]))
    features = features.dropna()
    if features.empty:
        raise ValueError("No complete scenario windows across the seven services")
    labels = features.index.get_level_values("test").to_numpy()
    groups = features.index.get_level_values("run")
    if len(set(groups)) < 3:
        raise ValueError("At least three independent runs with complete windows are required")
    abnormal = labels != "correct"
    if any(len(set(abnormal[groups == run])) != 2 for run in set(groups)):
        raise ValueError("Each run must contain correct and error scenarios")
    x = np.log1p(features.to_numpy())
    predictions = []
    for train, test in GroupKFold(n_splits=min(5, len(set(groups)))).split(x, groups=groups):
        normal = x[train][~abnormal[train]]
        scaler = RobustScaler().fit(normal)
        deviations = np.abs(scaler.transform(x[test]))
        scores = np.median(deviations, axis=1)
        service_scores = np.median(deviations.reshape(-1, len(SIGNALS), len(SERVICES)), axis=1)
        classifier = RandomForestClassifier(n_estimators=150, random_state=42, class_weight="balanced")
        errors = train[abnormal[train]]
        classifier.fit(x[errors], labels[errors])
        scenario_order = np.argsort(-classifier.predict_proba(x[test]), axis=1, kind="stable")
        for i, idx in enumerate(test):
            ranked = scenario_order[i]
            services = np.argsort(-service_scores[i], kind="stable")
            predictions.append({
                "run": groups[idx], "test": labels[idx], "error": bool(abnormal[idx]),
                "score": scores[i], "scenario_top1": classifier.classes_[ranked[0]],
                "scenario_top3": "|".join(classifier.classes_[ranked[:3]]),
                "service_ranking": "|".join(SERVICES[j] for j in services),
            })
    return pd.DataFrame(predictions)


def main(workers):
    paths = sorted(RAW.glob("*.csv"))
    if not paths:
        raise SystemExit("No metric files found. Run python -m src.download first.")
    timings = {}
    table = None
    for count in sorted({1, workers}):
        samples = []
        for _ in range(3):
            start = perf_counter()
            candidate = collect(paths, count)
            samples.append(perf_counter() - start)
            if table is None:
                table = candidate
            else:
                pd.testing.assert_frame_equal(table, candidate)
        timings[str(count)] = round(float(np.median(samples)), 3)
    results = evaluate(table)
    errors = results[results.error]
    report = {
        "files": len(paths),
        "input_bytes": sum(path.stat().st_size for path in paths),
        "runs": results.run.nunique(),
        "scenario_windows": len(results),
        "scenarios": results.test.nunique(),
        "error_prevalence": results.error.mean(),
        "roc_auc": roc_auc_score(results.error, results.score),
        "average_precision": average_precision_score(results.error, results.score),
        "scenario_top1": (errors.test == errors.scenario_top1).mean(),
        "scenario_top3": np.mean([label in choices.split("|") for label, choices in zip(
            errors.test, errors.scenario_top3)]),
        "scenario_balanced_accuracy": balanced_accuracy_score(errors.test, errors.scenario_top1),
        "preprocessing_median_seconds": timings,
    }
    output = Path("results")
    output.mkdir(exist_ok=True)
    results.to_csv(output / "predictions.csv", index=False)
    table.to_parquet(Path("data/processed") / "scenario_features.parquet", index=False)
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate LO2v2 metrics baselines")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    main(args.workers)
