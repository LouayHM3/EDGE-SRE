"""Exercise a disposable local Kafka broker and restart the Spark consumer."""

import base64
import argparse
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import KafkaError
import numpy as np
import pandas as pd

from streaming.replay import replay
from src.preprocess import OUTPUT

FIRST = 96
TOTAL = 256
DUPLICATE = 16
TOPIC = "lo2v2-replay"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def create_topic(broker, process):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with KafkaAdminClient(bootstrap_servers=broker, request_timeout_ms=3000) as admin:
                admin.create_topics([NewTopic(TOPIC, 1, 1)])
            return
        except (OSError, KafkaError):
            time.sleep(0.5)
    raise RuntimeError("Local Kafka broker failed to create the topic; inspect broker.log")


def wait_for_predictions(database, process, count):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and process.poll() is None:
        if database.is_file():
            with closing(sqlite3.connect(database)) as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'predictions' AND type = 'table'"
                ).fetchone()
                if table and connection.execute("SELECT count(*) FROM predictions").fetchone()[0] == count:
                    return
        time.sleep(0.25)
    raise RuntimeError(f"Consumer did not persist {count} predictions; inspect consumer-continuous.log")


def run_continuous(consumer, broker, directory, database):
    runs = [(2, 80), (10, 80)]
    with (directory / "consumer-continuous.log").open("w", encoding="utf-8") as out:
        process = subprocess.Popen(consumer, stdout=out, stderr=subprocess.STDOUT)
        try:
            assert replay(broker, TOPIC, limit=FIRST) == FIRST
            wait_for_predictions(database, process, FIRST)
            print(f"Warm-up complete: {FIRST} predictions", flush=True)
            cursor = FIRST
            for rate, count in runs:
                assert replay(broker, TOPIC, start=cursor, limit=count, rate=rate) == count
                cursor += count
                wait_for_predictions(database, process, cursor)
                print(f"Recorded {count} predictions at a target of {rate}/s", flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)

    with closing(sqlite3.connect(database)) as connection:
        predictions = pd.read_sql_query("SELECT * FROM predictions", connection)
    keys = ["run", "test", "window_start"]
    ordered = pd.read_parquet(OUTPUT / "windows_test.parquet", columns=keys)
    ordered = ordered.sort_values(["window_start", "run", "test"]).iloc[:cursor].copy()
    ordered["window_start"] = ordered.window_start.dt.as_unit("s").astype("int64")
    measurements = ordered.merge(predictions, on=keys, how="left", validate="one_to_one", sort=False)
    assert measurements.event_id.notna().all() and len(predictions) == cursor
    offline = pd.read_csv("results/spark_predictions.csv")
    matched = predictions.merge(offline, on=keys, validate="one_to_one")
    assert len(matched) == cursor
    np.testing.assert_allclose(matched.score_x, matched.score_y, rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(matched.alert_x.astype(bool), matched.alert_y)
    latencies = []
    cursor = FIRST
    for rate, count in runs:
        batch = measurements.iloc[cursor:cursor + count]
        delay = (batch.scored_at_ms - batch.published_at_ms) / 1000
        elapsed = (batch.scored_at_ms.max() - batch.published_at_ms.min()) / 1000
        producer_span = (batch.published_at_ms.max() - batch.published_at_ms.min()) / 1000
        latencies.append({
            "target_windows_per_second": rate, "windows": count,
            "observed_publish_windows_per_second": (count - 1) / producer_span,
            "end_to_end_windows_per_second": count / elapsed,
            "median_seconds": float(delay.median()), "p95_seconds": float(delay.quantile(0.95)),
        })
        cursor += count
    summary = {
        "simulated": True, "warmup_windows_excluded": FIRST,
        "trigger_seconds": 2, "batch_parity_verified": True, "measurements": latencies,
        "directory": directory.relative_to(Path.cwd()).as_posix(),
    }
    Path("results/streaming_continuous.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuous", action="store_true", help="Measure paced replay latency")
    args = parser.parse_args()
    tools = Path(sys.prefix) / "tools"
    java = next(tools.glob("*/bin/java.exe")).resolve()
    kafka = tools / "kafka_2.13-4.1.2"
    classpath = str(kafka.resolve() / "libs" / "*")
    directory = (Path("results") / f"streaming-{uuid4().hex[:10]}").resolve()
    directory.mkdir(parents=True)
    config = directory / "server.properties"
    broker_port, controller_port = port(), port()
    while controller_port == broker_port:
        controller_port = port()
    broker = f"127.0.0.1:{broker_port}"
    controller = f"127.0.0.1:{controller_port}"
    config.write_text(f"""process.roles=broker,controller
node.id=1
controller.quorum.bootstrap.servers={controller}
listeners=PLAINTEXT://{broker},CONTROLLER://{controller}
advertised.listeners=PLAINTEXT://{broker}
controller.listener.names=CONTROLLER
listener.security.protocol.map=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
inter.broker.listener.name=PLAINTEXT
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
group.initial.rebalance.delay.ms=0
auto.create.topics.enable=false
log.dirs={(directory / "broker-data").as_posix()}
""", encoding="ascii")
    log = directory / "broker.log"
    logging_config = (kafka / "config" / "log4j2.yaml").resolve().as_uri()
    command = [str(java), "-Xmx512m", f"-Dlog4j2.configurationFile={logging_config}", "-cp", classpath]
    cluster = base64.urlsafe_b64encode(uuid4().bytes).decode().rstrip("=")
    subprocess.run(
        [*command, "kafka.tools.StorageTool", "format", "--standalone",
         "-t", cluster, "-c", str(config)], cwd=directory, check=True, timeout=60,
    )
    database = directory / "predictions.sqlite"
    consumer = [sys.executable, "-m", "streaming.consumer", "--broker", broker, "--topic", TOPIC,
                "--checkpoint", str(directory / "checkpoint"), "--database", str(database)]

    def consume(index):
        with (directory / f"consumer-{index}.log").open("w", encoding="utf-8") as out:
            subprocess.run([*consumer, "--available-now"], stdout=out,
                           stderr=subprocess.STDOUT, check=True, timeout=240)

    print(f"Demo artifacts: {directory}", flush=True)
    with log.open("w", encoding="utf-8") as out:
        process = subprocess.Popen([*command, "kafka.Kafka", str(config)],
                                   cwd=directory, stdout=out, stderr=subprocess.STDOUT)
        try:
            create_topic(broker, process)
            print("Local Kafka ready", flush=True)
            if args.continuous:
                run_continuous(consumer, broker, directory, database)
                return
            assert replay(broker, TOPIC, limit=FIRST) == FIRST
            consume(1)
            with sqlite3.connect(database) as connection:
                before = connection.execute("SELECT count(*), max(batch_id) FROM predictions").fetchone()
            assert before[0] == FIRST
            print(f"First consumer wrote {before[0]} rows and stopped", flush=True)
            assert replay(broker, TOPIC, start=FIRST, limit=TOTAL - FIRST) == TOTAL - FIRST
            assert replay(broker, TOPIC, limit=DUPLICATE) == DUPLICATE
            consume(2)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)

    with sqlite3.connect(database) as connection:
        predictions = pd.read_sql_query("SELECT * FROM predictions ORDER BY run, test, window_start", connection)
    assert len(predictions) == TOTAL
    assert (predictions.batch_id > before[1]).sum() == TOTAL - FIRST
    progress = (directory / "consumer-2.log").read_text(encoding="utf-8", errors="replace")
    batches = [batch for line in progress.splitlines() if line.startswith('[{"batch"')
               for batch in json.loads(line)]
    assert sum(batch["input_rows"] for batch in batches) == TOTAL - FIRST + DUPLICATE, batches
    offline = pd.read_csv("results/spark_predictions.csv")
    matched = predictions.merge(offline, on=["run", "test", "window_start"], validate="one_to_one")
    assert len(matched) == TOTAL
    np.testing.assert_allclose(matched.score_x, matched.score_y, rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(matched.alert_x.astype(bool), matched.alert_y)
    summary = {
        "simulated": True, "published": TOTAL + DUPLICATE, "unique_predictions": TOTAL,
        "first_consumer": FIRST, "after_restart": TOTAL - FIRST,
        "duplicate_events_ignored": DUPLICATE, "alerts": int(predictions.alert.sum()),
        "median_publish_to_sink_ms": float((predictions.scored_at_ms - predictions.published_at_ms).median()),
        "directory": str(directory.relative_to(Path.cwd())),
    }
    (Path("results") / "streaming_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
