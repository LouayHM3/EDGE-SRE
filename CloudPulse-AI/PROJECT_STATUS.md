# Project status

The CPU-based LO2v2 metrics benchmark is implemented. The project uses a
local Python 3.11 environment and the CloudPulse AI Jupyter kernel.

- **Data acquisition** uses the official Zenodo metrics archive. The local
  sample covers ten collection runs and seven application services per run.
- **Exploration** uses a notebook with class balance, feature missingness,
  and the held-out ROC curve.
- **Modeling** evaluates a normal-reference detector and supervised API
  error scenario ranking with run-disjoint folds. Service deviation rankings
  provide leads for investigation.
- **Processing** benchmarks local serial and multiprocess preprocessing
  against the same files and checks that their outputs agree.

See the [README](README.md) for commands and the
[benchmark report](reports/metrics-benchmark.md) for the evaluation and
its limits. Logs, traces, distributed processing, and validated causal
service localization are outside this metrics benchmark.

## Roadmap and validation

Phase 0 established the Python environment and Jupyter kernel. Java and
Spark compatibility will be addressed before Spark integration.

Phase 1 exploration was executed and approved by the user. See the
[dataset exploration report](reports/dataset-exploration.md) for the
official archive inventory, annotation limits, and audit of 387,219
observations.

Phase 2 was implemented and executed in the
[preprocessing notebook](notebooks/02_data_preprocessing.ipynb).
Seven services are aligned on UTC timestamps. The pipeline uses complete
20-second windows at a 10-second stride and standardizes 98 window features
using training statistics. The 4,207 windows are split by collection run
into 2,516 training, 857 validation, and 834 test windows. Only 71 windows
represent the normal scenario. Phase 2 was approved by the user.

Phase 3 was implemented and executed in the [ML baseline notebook](notebooks/03_ml_baseline.ipynb).
On the fixed test split, Random Forest achieved 0.801 ROC AUC and
0.775 balanced accuracy for API error detection, with 2 false alarms
among 11 normal windows. The HTTP-status classifier achieved 56.7% top-1
accuracy versus a 54.7% majority-class reference. The 53-scenario classifier
achieved 7.9% top-1 and 20.4% top-3 accuracy. The test windows overlap and
come from two runs, so the results are preliminary. The user authorized
continuation to Phase 4.

Phase 4 was implemented and executed on CPU in the
[deep learning notebook](notebooks/04_deep_learning.ipynb). The dense
autoencoder achieved 0.708 ROC AUC and 20.4% recall at the validation
threshold, with zero false positives among 11 normal test windows.
The LSTM forecaster, LSTM autoencoder, TCN forecaster, and Transformer
forecaster achieved ROC AUC values of 0.381, 0.553, 0.387, and 0.464.
Random Forest retained the highest ROC AUC (0.801) on this split.
The deep models trained on 54 normal windows. The user authorized
continuation to Phase 5.

Phase 5 was implemented and executed in the
[log intelligence notebook](notebooks/05_log_intelligence.ipynb).
The sampler read 40 token-service logs totaling 4.45 MB of compressed
members across 10 runs and four known scenarios. The TF-IDF template
baseline and small Transformer both reached 1.000 ROC AUC on eight
held-out run-scenario pairs. The metrics-only Random Forest and equal-weight
fusion both reached 0.667 ROC AUC. This experiment measures known-scenario
transfer across two test runs. The labels describe client API requests
and do not establish production detection or causal attribution.
The user authorized continuation to Phase 6.

Phase 6 was implemented and executed in the
[root cause analysis notebook](notebooks/06_root_cause_analysis.ipynb).
It ranked seven services across 108 held-out run-scenario pairs and
examined onset and lagged associations. In the example `get_token_404`,
the `service` container exceeded its reference in 37.8% of observed
seconds versus 29.7% in the correct scenario from the same run. No
service exceeded its threshold for three consecutive seconds in that
error example. Causal accuracy and dependency edges were not evaluated
because the sample lacks verified ground truth. The user authorized
continuation to Phase 7.

Phase 7 local Spark preprocessing and inference were executed and verified
in the [Spark notebook](notebooks/07_spark_integration.ipynb). Spark 4.1.3 on
Java 17 produced all 4,207 Pandas reference windows within the numeric
tolerance. Worker inference reproduced the 834 central test scores within
tolerance and all alert decisions. The local run used `local[2]`. The pip
build stalled, so the verified PyPI source distribution was used directly.
The HDFS input and output paths are implemented and documented in the
[Spark and HDFS guide](docs/spark-hdfs.md). A live HDFS endpoint and a
multi-worker cluster are still needed to validate storage and cluster
execution. The user authorized continuation to Phase 8.

Phase 8 local benchmarking was executed in the
[performance notebook](notebooks/08_performance_benchmark.ipynb). Median
preprocessing time for 10 runs was 4.31 s in Pandas, 14.43 s in Spark
with two partitions, and 13.41 s with four partitions. Reusing cached Spark
features took 2.03 s versus 3.96 s uncached. Feature and inference parity
checks passed. The benchmark records throughput, process-tree CPU and RSS
estimates, and inference latency. Multi-worker and HDFS measurements still
require a live cluster. The user approved progression to Phase 9.

Phase 9 was verified end to end on one Windows host with Kafka 4.1.2,
Spark Structured Streaming, and the dense PyTorch checkpoint. The demo
published 272 simulated events, persisted 256 unique predictions, and
ignored 16 duplicates. A fresh consumer resumed from the same checkpoint
and added 160 predictions after the initial 96. All scores matched the
batch reference within tolerance, and all 53 alerts matched. Median
publish-to-sink latency was 31.1 s in the burst replay with AvailableNow
and separate JVM launches. Multi-node recovery remains unmeasured.
See the [streaming guide](docs/streaming.md).
The user authorized continuation to Phase 10.

Phase 10 was implemented and verified locally. MLflow registered
`cloudpulse-dense-autoencoder` version 1 and the stored checkpoint hash
was verified. The FastAPI HTTP test matched offline inference and
checked replay results, service rankings, validation errors, and metric
exposition. Prometheus scraped the API and Grafana returned the same
53 simulated alerts from its datasource. The local dashboard has seven
panels. Docker Compose was also built and verified with Docker Desktop
and WSL 2. The containerized API reproduced the reference prediction,
Prometheus reported the API target up, and Grafana returned all 53
simulated replay alerts from the Prometheus data source. The Windows
build required the host's Avast public CA as a temporary build secret.

After the local Phase 10 milestone, the continuous Kafka/Spark replay was
verified on one Windows host. After excluding 96 warm-up windows, two
groups of 80 verified windows yielded median latencies of 9.85 s and
9.26 s at observed publish rates of 1.99 and 9.80 windows/s. The p95
latencies were 12.77 s and 12.16 s. Results are in
`results/streaming_continuous.json`.

The Docker HDFS and Spark lab was verified on one physical host.
HDFS fsck confirmed two live copies of each of 70 input blocks on
distinct DataNodes. Both Spark workers scored windows in every
standalone trial. The job matched 4,207 feature windows, 834 predictions,
and 168 alerts and verified its HDFS Parquet output by reading it back.
For ten runs, median preprocessing time was 22.72 s in local Spark and
16.53 s with two workers. For two runs the times were 15.47 s and
21.02 s, respectively. See the [benchmark notebook](notebooks/08_performance_benchmark.ipynb)
and [lab guide](docs/spark-hdfs.md).

Cross-host performance and failure recovery require separate physical
hosts. Infrastructure fault classification and causal service
evaluation depend on suitable labels.

With user approval, the Windows Subsystem for Linux and Virtual Machine
Platform features were enabled with DISM. Both operations returned 3010,
so a Windows restart is required before validating WSL 2 and Docker.
The verified Microsoft MSI installed WSL 3.0.5 successfully. The
Docker Desktop 4.100.1 installer was downloaded to `.venv/tools` and
its Docker Inc. signature was verified. After Windows restarted, WSL
reported version 2 as the default. Docker Desktop 4.100.1 is installed
and the Compose stack is running.
