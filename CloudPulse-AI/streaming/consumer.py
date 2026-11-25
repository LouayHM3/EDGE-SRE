"""Score historical replay micro-batches from Kafka using Structured Streaming."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import time

from spark.lo2_pipeline import CHECKPOINT, KEYS, session, worker_scores
from pyspark.sql import functions as F

from src.preprocess import OUTPUT
from streaming.kafka_jars import ARTIFACTS, JARS

SCHEMA = """event_id string, run string, test string, window_start long,
            features array<double>, simulated boolean, published_at_ms long"""
MAX_OFFSETS = 128


def save_batch(frame, batch_id, database, features, checkpoint_payload):
    events = frame.persist()
    try:
        invalid = events.where(
            F.col("event_id").isNull() | F.col("run").isNull() | F.col("test").isNull()
            | F.col("window_start").isNull() | F.col("published_at_ms").isNull()
            | ~F.col("simulated").eqNullSafe(True)
            | F.col("features").isNull() | (F.size("features") != len(features))
            | F.exists("features", lambda value: value.isNull() | F.isnan(value) | (F.abs(value) == float("inf")))
        )
        if invalid.limit(1).count():
            raise ValueError("Kafka batch contains an invalid simulated feature event")
        rows = events.select("event_id", *KEYS, "published_at_ms").toPandas()
        if rows.empty:
            return
        unique = events.dropDuplicates(KEYS)
        expanded = unique.select(
            *KEYS, *[F.col("features")[i].alias(name) for i, name in enumerate(features)],
        )
        predicted = worker_scores(expanded, CHECKPOINT, payload=checkpoint_payload).toPandas()
        output = rows.merge(predicted, on=KEYS, validate="many_to_one")
        time_ms = time.time_ns() // 1_000_000
        with sqlite3.connect(database) as connection:
            connection.executemany(
                """INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(event_id) DO NOTHING""",
                [
                    (row.event_id, row.run, row.test, row.window_start, float(row.score),
                     int(row.alert), int(batch_id), row.published_at_ms, time_ms)
                    for row in output.itertuples(index=False)
                ],
            )
    finally:
        events.unpersist()


def run(broker, topic, checkpoint, database, available_now=False):
    jars = [JARS / f"{name}-{version}.jar" for _, name, version in ARTIFACTS]
    if not all(path.is_file() for path in jars):
        raise RuntimeError("Run python -m streaming.kafka_jars first")
    if os.name == "nt":
        from streaming.windows_checkpoint import build
        jars.append(build())
    features = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))["feature_columns"]
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS predictions (
            event_id TEXT PRIMARY KEY, run TEXT NOT NULL, test TEXT NOT NULL,
            window_start INTEGER NOT NULL, score REAL NOT NULL, alert INTEGER NOT NULL,
            batch_id INTEGER NOT NULL, published_at_ms INTEGER NOT NULL, scored_at_ms INTEGER NOT NULL
        )""")
    spark = session("local[2]", 2, jars)
    spark.sparkContext.setLogLevel("ERROR")
    try:
        if os.name == "nt":
            spark.conf.set(
                "spark.sql.streaming.checkpointFileManagerClass",
                "cloudpulse.streaming.LocalCheckpointManager",
            )
        payload = spark.sparkContext.broadcast(CHECKPOINT.read_bytes())
        source = (spark.readStream.format("kafka").option("kafka.bootstrap.servers", broker)
                  .option("subscribe", topic).option("startingOffsets", "earliest")
                  .option("maxOffsetsPerTrigger", MAX_OFFSETS).load())
        events = source.select(F.from_json(F.col("value").cast("string"), SCHEMA).alias("event")).select("event.*")
        writer = (events.writeStream.option("checkpointLocation", checkpoint.resolve().as_uri())
                  .foreachBatch(lambda frame, batch: save_batch(frame, batch, database, features, payload)))
        writer = writer.trigger(availableNow=True) if available_now else writer.trigger(processingTime="2 seconds")
        query = writer.start()
        query.awaitTermination()
        print(json.dumps([
            {"batch": batch["batchId"], "input_rows": batch["numInputRows"],
             "trigger_ms": batch["durationMs"].get("triggerExecution")}
            for batch in query.recentProgress
        ]), flush=True)
    finally:
        spark.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default="127.0.0.1:9092")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--available-now", action="store_true")
    args = parser.parse_args()
    run(args.broker, args.topic, args.checkpoint, args.database, args.available_now)
