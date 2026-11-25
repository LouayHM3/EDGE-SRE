"""Prepare LO2v2 windows in Spark SQL and score them with PyTorch workers."""

import argparse
import io
import json
import os
import sys
from importlib.util import find_spec
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

if find_spec("pyspark") is None:
    # The verified PyPI source distribution can run directly when pip's wheel build stalls.
    source = Path(sys.prefix) / "tools" / "pyspark-4.1.3"
    bridge = next(source.glob("lib/py4j-*-src.zip"), None)
    if bridge is not None:
        locations = [str(source), str(bridge)]
        sys.path[:0] = locations
        os.environ.setdefault("SPARK_HOME", str(source / "deps"))
        previous = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = os.pathsep.join(locations + ([previous] if previous else []))

from pyspark.sql import SparkSession, Window, functions as F

from src.download import RAW, SERVICES
from src.preprocess import COUNTERS, GAUGES, OUTPUT, STRIDE, WINDOW as WINDOW_SECONDS

SIGNALS = GAUGES + COUNTERS
KEYS = ["run", "test", "window_start"]
CHECKPOINT = Path("models/dense_autoencoder.pt")


def session(master, partitions, jars=()):
    tools = Path(sys.prefix) / "tools"
    java = next(tools.glob("*/bin/java.exe"), None)
    if java is not None:
        os.environ.setdefault("JAVA_HOME", str(java.parent.parent))
    if master.startswith("local"):
        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
        os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")
    builder = (
        SparkSession.builder.master(master).appName("CloudPulse LO2v2")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", str(partitions))
        .config("spark.ui.enabled", "false")
    )
    if jars:
        if master.startswith("local"):
            classpath = os.pathsep.join(str(Path(jar).resolve()) for jar in jars)
            builder = builder.config("spark.driver.extraClassPath", classpath)
        else:
            builder = builder.config("spark.jars", ",".join(jars))
    return builder.getOrCreate()


def finite(column):
    return column.isNotNull() & ~F.isnan(column) & (F.abs(column) != float("inf"))


def read_aligned(spark, source, partitions):
    raw = spark.read.option("header", True).csv(source)
    aliases = F.create_map(*[
        item for service in SERVICES for item in (
            F.lit(f"light-oauth2-oauth2-{service}-1"), F.lit(service),
        )
    ])
    clean = raw.select(
        "run", "test", aliases[F.col("container")].alias("service"),
        F.col("timestamp").try_cast("long").alias("second"),
        *[F.col(name).try_cast("double").alias(name) for name in SIGNALS],
    ).dropna(subset=["run", "test", "service", "second"]).dropDuplicates()
    clean = clean.select(
        "run", "test", "service", "second",
        *[F.when(finite(F.col(name)), F.col(name)).alias(name) for name in SIGNALS],
    )
    keys = ["run", "test", "service", "second"]
    if clean.groupBy(*keys).count().where(F.col("count") > 1).limit(1).count():
        raise ValueError("Conflicting LO2v2 observation keys")
    order = Window.partitionBy("run", "test", "service").orderBy("second")
    elapsed = F.col("second") - F.lag("second").over(order)
    rates = []
    for name in COUNTERS:
        delta = F.col(name) - F.lag(name).over(order)
        rates.append(F.when((elapsed == 1) & (delta >= 0), delta).alias(name))
    rates = clean.select(*keys, *GAUGES, *rates)
    by_second = rates.groupBy("run", "test", "second").pivot("service", list(SERVICES)).agg(
        *[F.first(name).alias(name) for name in SIGNALS]
    )
    return by_second.repartition(partitions, "run", "test")


def build_windows(aligned, metadata):
    signal_columns = [f"{service}_{name}" for service in SERVICES for name in SIGNALS]
    earliest = F.min("second").over(Window.partitionBy("run", "test"))
    anchored = aligned.withColumn("origin", earliest)
    complete = F.lit(True)
    for name in signal_columns:
        complete = complete & finite(F.col(name))
    # A second can belong to the current stride or the preceding stride.
    current = F.floor((F.col("second") - F.col("origin")) / STRIDE) * STRIDE + F.col("origin")
    candidates = anchored.where(complete).withColumn(
        "window_start", F.explode(F.array(current, current - STRIDE)),
    ).where((F.col("window_start") >= F.col("origin")) & (
        F.col("second") < F.col("window_start") + WINDOW_SECONDS
    ))
    aggregations = []
    for service in SERVICES:
        for name in SIGNALS:
            signal = F.col(f"{service}_{name}")
            aggregations.extend([
                F.avg(signal).alias(f"{service}__{name}__mean"),
                F.stddev_pop(signal).alias(f"{service}__{name}__std"),
            ])
    grouped = candidates.groupBy(*KEYS).agg(F.count("*").alias("samples"), *aggregations)
    labels = F.create_map(*[
        item for split, runs in metadata["runs"].items()
        for run in runs for item in (F.lit(run), F.lit(split))
    ])
    expressions = [
        ((F.col(name) - mean) / scale).alias(name)
        for name, mean, scale in zip(
            metadata["feature_columns"], metadata["scaler_mean"], metadata["scaler_scale"], strict=True,
        )
    ]
    return grouped.where(F.col("samples") == WINDOW_SECONDS).select(
        *KEYS, labels[F.col("run")].alias("split"), (F.col("test") != "correct").alias("error"),
        *expressions,
    )


def worker_scores(frame, checkpoint, payload=None, include_worker=False):
    if payload is None:
        payload = frame.sparkSession.sparkContext.broadcast(Path(checkpoint).read_bytes())

    def score_batches(iterator):
        import socket
        import torch
        from src.deep_learning import build_autoencoder, score

        torch.set_num_threads(1)
        saved = torch.load(io.BytesIO(payload.value), map_location="cpu", weights_only=True)
        features = saved["feature_columns"]
        model = build_autoencoder(len(features))
        model.load_state_dict(saved["state_dict"])
        model.eval()
        for batch in iterator:
            inputs = torch.from_numpy(batch[features].to_numpy(dtype=np.float32, copy=True))
            scores = score(model, inputs).numpy().astype(float)
            result = batch[KEYS].assign(score=scores, alert=scores >= saved["threshold"])
            if include_worker:
                result["worker"] = socket.gethostname()
            yield result

    schema = "run string, test string, window_start long, score double, alert boolean"
    if include_worker:
        schema += ", worker string"
    return frame.mapInPandas(score_batches, schema)


def verify_features(windows, metadata):
    columns = metadata["feature_columns"]
    expected = pd.concat(
        [pd.read_parquet(OUTPUT / f"windows_{split}.parquet") for split in metadata["runs"]],
        ignore_index=True,
    )
    expected["window_start"] = expected.window_start.dt.as_unit("s").astype("int64")
    actual = windows.toPandas().sort_values(KEYS).reset_index(drop=True)
    expected = expected.sort_values(KEYS).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[KEYS + ["split", "error"]], expected[KEYS + ["split", "error"]],
                                  check_dtype=False)
    np.testing.assert_allclose(actual[columns], expected[columns], rtol=1e-6, atol=1e-6)


def verify_scores(distributed, checkpoint):
    import torch
    from src.deep_learning import build_autoencoder, score

    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    features = saved["feature_columns"]
    expected = pd.read_parquet(OUTPUT / "windows_test.parquet")
    expected["window_start"] = expected.window_start.dt.as_unit("s").astype("int64")
    expected = expected.sort_values(KEYS).reset_index(drop=True)
    actual = distributed.reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[KEYS], expected[KEYS], check_dtype=False)
    model = build_autoencoder(len(features))
    model.load_state_dict(saved["state_dict"])
    inputs = torch.from_numpy(expected[features].to_numpy(dtype=np.float32, copy=True))
    scores = score(model.eval(), inputs).numpy()
    np.testing.assert_allclose(actual.score, scores, rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(actual.alert, scores >= saved["threshold"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default="local[2]")
    parser.add_argument("--partitions", type=int, default=4)
    parser.add_argument("--input-uri", help="Spark input URI or glob (defaults to cached CSV files)")
    parser.add_argument("--output-uri", help="Writable Spark filesystem URI, including hdfs://")
    parser.add_argument("--skip-local-verification", action="store_true")
    args = parser.parse_args()
    source = args.input_uri or [path.resolve().as_uri() for path in sorted(RAW.glob("*.csv"))]
    if not source:
        parser.error(f"No metrics CSVs in {RAW}")
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    spark = session(args.master, args.partitions)
    try:
        start = perf_counter()
        aligned = read_aligned(spark, source, args.partitions)
        windows = build_windows(aligned, metadata).cache()
        windows.explain(mode="simple")
        windows.createOrReplaceTempView("lo2_windows")
        counts = [row.asDict() for row in spark.sql(
            "SELECT split, count(*) AS windows FROM lo2_windows GROUP BY split ORDER BY split"
        ).collect()]
        if not args.skip_local_verification:
            verify_features(windows, metadata)
        test = windows.where(F.col("split") == "test")
        prediction = worker_scores(test, CHECKPOINT)
        if args.output_uri:
            root = args.output_uri.rstrip("/")
            windows.write.mode("errorifexists").partitionBy("split").parquet(root + "/windows")
            prediction.write.mode("errorifexists").parquet(root + "/predictions")
        else:
            scores = prediction.toPandas().sort_values(KEYS)
            if not args.skip_local_verification:
                verify_scores(scores, CHECKPOINT)
            Path("results").mkdir(exist_ok=True)
            scores.to_csv("results/spark_predictions.csv", index=False)
        summary = json.dumps({
            "spark_version": spark.version, "master": args.master, "counts": counts,
            "elapsed_seconds": perf_counter() - start,
        }, indent=2)
        if not args.output_uri:
            Path("results/spark_summary.json").write_text(summary + "\n", encoding="utf-8")
        print(summary)
        windows.unpersist()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
