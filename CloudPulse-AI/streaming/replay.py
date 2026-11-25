"""Publish LO2v2 feature windows as explicitly simulated Kafka events."""

import argparse
import hashlib
import json
import time

from kafka import KafkaProducer
import pandas as pd

from src.preprocess import OUTPUT


def replay(broker, topic, start=0, limit=None, rate=0):
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    features = metadata["feature_columns"]
    table = pd.read_parquet(OUTPUT / "windows_test.parquet").sort_values(["window_start", "run", "test"])
    table = table.iloc[start:None if limit is None else start + limit]
    producer = KafkaProducer(bootstrap_servers=broker, acks="all", enable_idempotence=True)
    try:
        pending = []
        for row in table.to_dict("records"):
            timestamp = int(row["window_start"].timestamp())
            key = [row["run"], row["test"], timestamp]
            event_id = hashlib.sha256(json.dumps(key).encode()).hexdigest()
            event = {
                "event_id": event_id, "run": key[0], "test": key[1], "window_start": timestamp,
                "features": [row[name] for name in features], "simulated": True,
                "published_at_ms": time.time_ns() // 1_000_000,
            }
            pending.append(producer.send(
                topic, key=event_id.encode(), value=json.dumps(event, allow_nan=False).encode(),
            ))
            if rate:
                time.sleep(1 / rate)
        for delivery in pending:
            delivery.get(timeout=30)
    finally:
        producer.close(timeout=10)
    return len(table)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default="127.0.0.1:9092")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rate", type=float, default=0, help="Maximum published windows per second")
    args = parser.parse_args()
    if args.start < 0 or args.rate < 0 or (args.limit is not None and args.limit < 0):
        parser.error("start, rate and limit must be nonnegative")
    print(f"Published {replay(args.broker, args.topic, args.start, args.limit, args.rate)} simulated events")
