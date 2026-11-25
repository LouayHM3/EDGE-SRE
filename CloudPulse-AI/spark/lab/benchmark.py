"""Measure identical HDFS workloads with local and standalone Spark."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from spark.lo2_pipeline import (
    CHECKPOINT, KEYS, build_windows, read_aligned, session, worker_scores,
)
from src.preprocess import OUTPUT

HDFS = "hdfs://namenode:8020/cloudpulse"
PARTITIONS = 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", required=True)
    parser.add_argument("--output-uri")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text())
    features = metadata["feature_columns"]
    reference = pd.concat(
        [pd.read_parquet(OUTPUT / f"windows_{split}.parquet") for split in metadata["runs"]],
        ignore_index=True,
    )
    reference["window_start"] = reference.window_start.dt.as_unit("s").astype("int64")
    offline = pd.read_csv("results/spark_predictions.csv")
    runs = sorted(reference.run.unique())
    spark = session(args.master, PARTITIONS)
    spark.sparkContext.setLogLevel("ERROR")
    records = []
    try:
        spark.range(1000).repartition(PARTITIONS).count()
        payload = spark.sparkContext.broadcast(CHECKPOINT.read_bytes())
        for count in (2, len(runs)):
            subset = runs[:count]
            paths = [f"{HDFS}/input/{run}-*.csv" for run in subset]
            expected = reference[reference.run.isin(subset)].sort_values(KEYS).reset_index(drop=True)
            expected_scores = offline[offline.run.isin(subset)].sort_values(KEYS).reset_index(drop=True)
            for repeat in range(1, args.repeats + 1):
                start = perf_counter()
                windows = build_windows(read_aligned(spark, paths, PARTITIONS), metadata).cache()
                try:
                    actual = windows.toPandas().sort_values(KEYS).reset_index(drop=True)
                    preprocess_time = perf_counter() - start
                    pd.testing.assert_frame_equal(actual[KEYS + ["split", "error"]],
                                                  expected[KEYS + ["split", "error"]], check_dtype=False)
                    np.testing.assert_allclose(actual[features], expected[features], rtol=1e-6, atol=1e-6)
                    testing = windows.where("split = 'test'").repartition(PARTITIONS)
                    scored = worker_scores(testing, CHECKPOINT, payload, include_worker=True)
                    start = perf_counter()
                    actual_scores = scored.toPandas().sort_values(KEYS).reset_index(drop=True)
                    inference_time = perf_counter() - start
                    pd.testing.assert_frame_equal(actual_scores[KEYS], expected_scores[KEYS], check_dtype=False)
                    np.testing.assert_allclose(actual_scores.score, expected_scores.score, rtol=1e-5, atol=1e-6)
                    np.testing.assert_array_equal(actual_scores.alert, expected_scores.alert)
                    record = {
                        "master": args.master, "runs": count, "repeat": repeat,
                        "preprocessing_seconds": preprocess_time, "inference_seconds": inference_time,
                        "windows": len(actual), "predictions": len(actual_scores),
                        "alerts": int(actual_scores.alert.sum()),
                        "inference_workers": sorted(actual_scores.worker.unique().tolist()),
                    }
                    records.append(record)
                    print("CLOUDPULSE_TRIAL " + json.dumps(record), flush=True)
                    if args.output_uri and count == len(runs) and repeat == args.repeats:
                        root = args.output_uri.rstrip("/")
                        windows.write.mode("errorifexists").partitionBy("split").parquet(root + "/windows")
                        scored.write.mode("errorifexists").parquet(root + "/predictions")
                        assert spark.read.parquet(root + "/windows").count() == len(actual)
                        assert spark.read.parquet(root + "/predictions").count() == len(actual_scores)
                finally:
                    windows.unpersist()
        if not args.master.startswith("local") and len({
            worker for record in records for worker in record["inference_workers"]
        }) < 2:
            raise RuntimeError("Only one worker executed inference")
        print("CLOUDPULSE_COMPLETE " + json.dumps({"master": args.master, "trials": len(records)}), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
