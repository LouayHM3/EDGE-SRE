# LO2v2 metrics benchmark

## Dataset and evaluation

The sample contains the seven application services for ten evenly spaced
runs from the official LO2v2 metrics archive. The dataset records tests
against Light-OAuth2. The correct test exercises valid requests. The
other scenarios exercise client requests that intentionally trigger API
errors. [LO2v2 archive](https://zenodo.org/records/18937117)
and [dataset descriptor](https://doi.org/10.1109/IEEEDATA.2026.3701668).

Each example summarizes the first 20 distinct timestamps per service
within a run and scenario. The features are median memory gauges and
median nonnegative counter rates for CPU, disk I/O, and network traffic.
The model inputs exclude timestamps, test names, run IDs, and window
length. Windows missing a usable signal for any service are omitted.

Five group folds hold out entire collection runs. The detector scores
median absolute feature deviations from a robust reference fit to correct
training windows. A random forest trained on error scenarios ranks their
test labels. The service ranking orders services by median deviation from
the normal reference and can guide inspection. The source provides
client-side error scenarios, so this benchmark has no causal-service
accuracy score.

## Reproduction

Use the commands in the [README](../README.md). The timing experiment
measures median wall time across three preprocessing passes per worker
count, including process startup and CSV reads. Both worker counts must
produce identical feature tables. Timings reflect this machine and
dataset size.

## Results

The sample contained 70 CSVs (170.5 MB) and produced 540 evaluable
windows across 54 scenarios. There were ten correct windows and 530
error windows.

| Measure | Held-out result | Reference |
| --- | ---: | ---: |
| Error detection ROC AUC | 0.619 | 0.500 for random ranking |
| Error detection average precision | 0.988 | 0.981 error prevalence |
| Error scenario top-1 accuracy | 3.4% | 1.9% uniform chance |
| Error scenario top-3 accuracy | 8.3% | 5.7% uniform chance |
| Serial preprocessing | 15.695 s | Three-pass median |
| Two-worker preprocessing | 11.426 s | Three-pass median |

The two-worker run was about 1.37x faster and produced identical features.
The detector showed limited separation. The high average precision is
close to the prevalence baseline because almost every window is an error
test. Scenario rankings performed only modestly above uniform chance.
These findings apply to this sampled, metrics-only workload. This benchmark
covers local CPU processing. Distributed processing and multimodal models
were outside the experiment.
