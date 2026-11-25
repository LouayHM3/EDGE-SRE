# Spark and HDFS integration

## Local Spark

Use Python 3.11, Java 17, PySpark 4.1.3, and the PyTorch CPU build
documented in the README. Set JAVA_HOME to a Java 17 installation or
place the extracted Java runtime under .venv/tools, as used locally.
Run from the project root after preprocessing and dense model training.

```powershell
.\.venv\Scripts\python.exe -m pip install pyspark==4.1.3
.\.venv\Scripts\python.exe -m spark.lo2_pipeline
```

The local build dependency subprocess stalled during installation. The
verified [PyPI source distribution](https://pypi.org/project/pyspark/4.1.3/#files)
was extracted into `.venv/tools/pyspark-4.1.3` and used for the run.
The module discovers this layout if the installed package is absent.
The Windows local reader passes explicit CSV paths to Hadoop, which
avoids native directory globbing.

The local job reads 70 CSVs, checks conflicting keys, derives rates with
an ordered Spark window, and pivots observations to one row per second.
Overlapping windows are aggregated on executors. A SQL action materializes
the cache. Phase 2 split assignments and scaler values are reused to
compare equivalent inputs. The small local reference check collects
results to the driver. Use a size-appropriate distributed sink in
cluster runs.

## HDFS data path

The Spark driver and executors must resolve the HDFS NameNode and be able
to reach DataNodes. Use the cluster Hadoop configuration and an account
with access to a dedicated project directory. The PyTorch, Pandas and
Arrow runtime and the project Python modules must be installed or
distributed to each Spark worker. Provide the driver with the preprocessing
metadata and the checkpoint. Set the worker Python executable to the
environment configured by the cluster.

From a machine with the Hadoop client configured, replace the example
NameNode and project paths with the authorized endpoints. Use a fresh
output directory for each run.

```bash
hdfs dfs -mkdir -p hdfs://namenode.example:8020/cloudpulse/input
hdfs dfs -put data/raw/metrics/*.csv hdfs://namenode.example:8020/cloudpulse/input/
python -m spark.lo2_pipeline \
  --input-uri 'hdfs://namenode.example:8020/cloudpulse/input/*.csv' \
  --output-uri 'hdfs://namenode.example:8020/cloudpulse/output/run-01'
hdfs dfs -ls -R hdfs://namenode.example:8020/cloudpulse/output/run-01
hdfs fsck /cloudpulse/output/run-01 -files -blocks -locations
```

The example uses local Spark compute with shared HDFS storage. To
exercise separate executors, use the cluster's master endpoint with
`--master` and its configured Python environment. HDFS splits files into
blocks and uses DataNodes for replicated storage. Spark partitions
govern shuffle and task placement. Inspect actual block locations and
replication before making a claim about storage fault tolerance.

[Apache Spark PySpark installation](https://spark.apache.org/docs/4.1.3/api/python/getting_started/install.html)
and [Apache Hadoop HDFS architecture](https://hadoop.apache.org/docs/current/hadoop-project-dist/hadoop-hdfs/HdfsDesign.html).

## Private Docker lab

The lab uses a NameNode, two DataNodes, a Spark master and two Spark
workers on a private Docker network. It requires the monitoring API
image built by the main Compose stack and the verified PySpark 4.1.3
source distribution extracted into `.venv/tools/pyspark-4.1.3`.
Build the shared driver and worker image before starting the services.

```powershell
docker compose -f spark/lab/compose.yml build driver
docker compose -f spark/lab/compose.yml up -d namenode datanode-a datanode-b master worker-a worker-b
docker compose -f spark/lab/compose.yml exec -T namenode hdfs dfsadmin -report
```

When both DataNodes are live, seed a fresh lab and check block locations.

```powershell
docker compose -f spark/lab/compose.yml exec -T namenode bash -ec 'hdfs dfsadmin -safemode wait; hdfs dfs -mkdir -p /cloudpulse/input; hdfs dfs -put /input/*.csv /cloudpulse/input/; hdfs dfs -setrep -w 2 /cloudpulse/input; hdfs fsck /cloudpulse/input -files -blocks -locations'
```

These runs use the same HDFS inputs, four shuffle partitions, two Spark
cores, checkpoint, collected outputs, and numeric verification. Each
configuration runs two trials for two and ten source runs. The standalone
trial also writes and reads Parquet on HDFS after the timed portion.
Use a fresh output directory when repeating the standalone command.

```powershell
docker compose -f spark/lab/compose.yml run --no-deps --rm --use-aliases driver 'python -m spark.lab.benchmark --master local\[2\]'
docker compose -f spark/lab/compose.yml run --no-deps --rm --use-aliases driver 'python -m spark.lab.benchmark --master spark://master:7077 --output-uri hdfs://namenode:8020/cloudpulse/output/run-01'
```

The lab records each worker hostname during inference. All containers
share one host, so this experiment measures a multi-worker deployment
and replicated blocks without measuring performance or availability
across physical hosts. Named Docker volumes preserve the NameNode metadata
and each DataNode's blocks when their containers are recreated.
