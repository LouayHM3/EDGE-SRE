"""Benchmark equivalent LO2v2 workloads on the local machine."""

import json
from pathlib import Path
from threading import Event, Thread
from time import perf_counter

import numpy as np
import pandas as pd
import psutil

from spark.lo2_pipeline import (
    CHECKPOINT, KEYS, build_windows, read_aligned, session, worker_scores,
)
from src.download import RAW
from src.preprocess import OUTPUT, load_aligned, make_windows

REPEATS = 2
SAMPLING_SECONDS = 0.2


def timed(action):
    process = psutil.Process()
    samples = {}
    rss = []
    stop = Event()

    def sample():
        total = 0
        for child in [process, *process.children(recursive=True)]:
            try:
                cpu = child.cpu_times()
                elapsed = cpu.user + cpu.system
                first, _ = samples.get(child.pid, (elapsed, elapsed))
                samples[child.pid] = first, elapsed
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        rss.append(total)

    def monitor():
        while not stop.wait(SAMPLING_SECONDS):
            sample()

    sample()
    sampler = Thread(target=monitor, daemon=True)
    sampler.start()
    start = perf_counter()
    try:
        value = action()
    finally:
        seconds = perf_counter() - start
        stop.set()
        sampler.join()
        sample()
    return value, {
        "seconds": seconds,
        "peak_tree_rss_mib": max(rss) / 2**20,
        "cpu_cores_equivalent": (
            sum(last - first for first, last in samples.values()) / seconds
            if seconds >= SAMPLING_SECONDS else None
        ),
    }


def pandas_windows(paths, metadata):
    table, features = make_windows(load_aligned(paths))
    table["window_start"] = table.window_start.dt.as_unit("s").astype("int64")
    table[features] = (table[features] - metadata["scaler_mean"]) / metadata["scaler_scale"]
    return table


def verify(actual, expected, features):
    actual = actual.sort_values(KEYS).reset_index(drop=True)
    expected = expected.sort_values(KEYS).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[KEYS + ["error"]], expected[KEYS + ["error"]], check_dtype=False)
    np.testing.assert_allclose(actual[features], expected[features], rtol=1e-6, atol=1e-6)


def main():
    import torch
    from src.deep_learning import build_autoencoder, score

    torch.set_num_threads(2)
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    features = metadata["feature_columns"]
    paths = sorted(RAW.glob("*.csv"))
    runs = sorted({path.name.split("-")[0] for path in paths})
    spark = session("local[2]", 4)
    spark.sparkContext.setLogLevel("ERROR")
    measurements = []

    def measure(stage, method, count, partitions, repeat, action, units=None):
        value, stats = timed(action)
        row = {"stage": stage, "method": method, "runs": count,
               "partitions": partitions, "repeat": repeat, "output_rows": len(value),
               "items_per_second": (units if units is not None else len(value)) / stats["seconds"],
               **stats}
        measurements.append(row)
        print(f"{stage} | {method} | {count} runs | {partitions} partitions | "
              f"{repeat}: {stats['seconds']:.3f}s", flush=True)
        return value

    try:
        spark.range(10).count()
        for group in (runs[:2], runs):
            count = len(group)
            subset = [path for path in paths if path.name.split("-")[0] in group]
            sources = [path.resolve().as_uri() for path in subset]
            expected = None
            for repeat in range(1, REPEATS + 1):
                expected = measure("preprocess", "Pandas", count, 0, repeat,
                                   lambda: pandas_windows(subset, metadata))
            for partitions in (2, 4):
                spark.conf.set("spark.sql.shuffle.partitions", str(partitions))
                for repeat in range(1, REPEATS + 1):
                    def end_to_end():
                        return build_windows(read_aligned(spark, sources, partitions), metadata).toPandas()
                    actual = measure("preprocess", "Spark", count, partitions, repeat, end_to_end)
                    verify(actual, expected, features)

        windows = build_windows(read_aligned(spark, sources, 4), metadata)
        for repeat in range(1, REPEATS + 1):
            actual = measure("reuse", "Spark uncached", len(runs), 4, repeat, windows.toPandas)
            verify(actual, expected, features)
        windows.cache()
        try:
            actual = measure("reuse", "Spark cache fill", len(runs), 4, 1, windows.toPandas)
            verify(actual, expected, features)
            for repeat in range(1, REPEATS + 1):
                actual = measure("reuse", "Spark cached", len(runs), 4, repeat, windows.toPandas)
                verify(actual, expected, features)

            test = windows.where("split = 'test'")
            saved = torch.load(CHECKPOINT, map_location="cpu", weights_only=True)
            model = build_autoencoder(len(features)).eval()
            model.load_state_dict(saved["state_dict"])
            split = pd.read_parquet(OUTPUT / "windows_test.parquet").sort_values(KEYS)
            inputs = torch.from_numpy(split[features].to_numpy(dtype=np.float32, copy=True))
            inferred = worker_scores(test, CHECKPOINT)
            score(model, inputs)
            inferred.toPandas()
            for repeat in range(1, REPEATS + 1):
                central = measure("inference", "Central PyTorch", len(metadata["runs"]["test"]), 0,
                                  repeat, lambda: score(model, inputs).numpy())
                distributed = measure("inference", "Spark PyTorch", len(metadata["runs"]["test"]), 4,
                                      repeat, inferred.toPandas).sort_values(KEYS)
                np.testing.assert_allclose(distributed.score, central, rtol=1e-5, atol=1e-6)
                np.testing.assert_array_equal(distributed.alert, central >= saved["threshold"])
        finally:
            windows.unpersist()
    finally:
        spark.stop()

    target = Path("results")
    target.mkdir(exist_ok=True)
    pd.DataFrame(measurements).to_csv(target / "spark_benchmark.csv", index=False)


if __name__ == "__main__":
    main()
