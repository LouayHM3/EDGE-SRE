# LO2v2 dataset exploration

## Source inventory

The [Zenodo record](https://zenodo.org/records/18937117) and
[dataset descriptor](https://doi.org/10.1109/IEEEDATA.2026.3701668)
describe metrics, Docker service logs, and Jaeger traces. The official
record lists the following files. Sizes are exact compressed download
sizes in bytes, except for the JSON index.

| File | Bytes | Verified contents |
| --- | ---: | --- |
| LO2v2-metrics.zip | 1,317,357,774 | Per-run CSV exports for host and container metrics |
| light-oauth2-metrics.zip | 77,564,351 | Example run with CSV and JSON members and Python scripts |
| LO2v2_index.json | 31,028,530 | A range read verified nested runs, tests, start/end timestamps, duration, and log file size and line counts |
| light-oauth2-logs.zip | 2,904,270,326 | ZIP directory contains 43,078 log files organized by run and scenario |
| LO2v2.zip | 65,613,664,046 | The descriptor documents the raw dataset, including traces |

Only selected members of the metrics export were used for the local
audit. The archive listings and the index prefix were inspected using
HTTP range requests. About 740 GB was available on disk at inspection.

## Local sample

The 70 CSVs contain 387,219 observations across 10 runs and seven
application services. All files share a 53-column schema. The fields
`run`, `test`, `container`, and `timestamp` identify an observation.
The sampled files contained zero missing cells, numeric infinities,
exact duplicate rows, duplicate observation keys, or unparseable
timestamps. These counts describe the selected sample.

There are 540 run-scenario pairs, including 10 instances of `correct`
and 530 error scenarios. The `test` field identifies the client API
scenario. Infrastructure failures and causal-service labels would require
additional ground truth. The notebook shows a same-service comparison
of CPU rates under a correct and an error scenario. This comparison
illustrates temporal behavior and cannot establish causality.

See the executed [exploration notebook](../notebooks/01_data_exploration.ipynb)
and the [prototype benchmark report](metrics-benchmark.md).
