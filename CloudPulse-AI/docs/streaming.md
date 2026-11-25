# Simulated Kafka streaming

The producer replays historical LO2v2 feature windows from the held-out
Parquet dataset. It emits normalized features in the order recorded by
preprocessing. Each Kafka event contains a stable identifier derived from
its run, scenario and timestamp, an explicit simulated flag, and the time
it was published. The original window time remains part of the event.

## Run the local demonstration

Install Kafka 4.1.2 under `.venv/tools/kafka_2.13-4.1.2`, and use the Java
17 and Spark 4.1.3 setup from the [Spark guide](spark-hdfs.md). The broker
distribution is published by [Apache Kafka](https://kafka.apache.org/41/getting-started/quickstart/).
The connector utility retrieves the Spark Kafka connector and required
additional jars from Maven Central. Run the Phase 7 Spark pipeline first
to create the offline score reference and keep the dense checkpoint and
preprocessing metadata from the same run.

```powershell
.\.venv\Scripts\python.exe -m pip install kafka-python==3.0.13
.\.venv\Scripts\python.exe -m streaming.kafka_jars
.\.venv\Scripts\python.exe -m streaming.demo
```

The demo binds a disposable single-node KRaft broker to loopback and
creates a fresh topic. It runs the Spark consumer twice with the same
checkpoint and SQLite database, publishes more windows between runs,
and deliberately republishes a subset of event IDs. It compares each
persisted score and alert with batch inference. The run directory in
`results/streaming_summary.json` contains the logs, checkpoint and local
database.

On Windows the consumer compiles a local checkpoint adapter using
Spark's bundled Scala compiler. It uses atomic same-directory moves on
the local filesystem and preserves the ACL inherited from the checkpoint
directory.

## Run against an existing broker

Create a dedicated topic and use a new checkpoint/database pair for an
independent replay. Keep the same pair when resuming. The consumer caps
micro-batches at 128 Kafka offsets. With the default continuous mode,
Spark requests a micro-batch every two seconds while the producer can
pace the replay independently.

```powershell
.\.venv\Scripts\python.exe -m streaming.consumer --topic lo2v2-replay --checkpoint results/stream-checkpoint --database results/stream-predictions.sqlite
.\.venv\Scripts\python.exe -m streaming.replay --topic lo2v2-replay --rate 10
```

Spark restores Kafka offsets from the checkpoint. A SQLite transaction
persists the predictions, with a unique event ID protecting the sink
from duplicate writes if the producer resends an event or an uncommitted
Spark batch is retried. The pipeline stops on an invalid event so it can
be investigated before resuming. The demo uses AvailableNow triggers and
measures replay latency on one machine, including queueing and startup.

[Spark Kafka integration](https://spark.apache.org/docs/4.1.2/streaming/structured-streaming-kafka-integration.html).

## Measure continuous replay

```powershell
.\.venv\Scripts\python.exe -m streaming.demo --continuous
```

The same consumer remains active with a two-second processing trigger.
After 96 warm-up windows are persisted, the producer sends 80 windows
at each of two target rates. The benchmark waits for the first group
to finish before sending the next. It reports measured publishing and
end-to-end throughput, median latency and p95 latency in
`results/streaming_continuous.json`. Latency starts at producer submission
and ends at the sink timestamp recorded just before the SQLite write.
Scores and alerts are compared with the offline Spark reference.
