"""Rank service deviations and inspect temporal associations on held-out runs."""

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from src.download import SERVICES
from src.preprocess import OUTPUT

KEYS = ["run", "test", "timestamp"]
RESULTS = Path("results")
PERSISTENCE = 3
MAX_LAG = 5
EXAMPLE = "get_token_404"


def service_scores(frame, normal):
    scores = pd.DataFrame(index=frame.index)
    for service in SERVICES:
        columns = [column for column in frame if column.startswith(f"{service}__")]
        reference = normal[columns].dropna()
        if reference.empty:
            raise ValueError(f"No complete normal reference for {service}")
        scale = reference.quantile(0.75) - reference.quantile(0.25)
        scale = scale.where(scale.gt(0), reference.std(ddof=0))
        usable = scale[scale.gt(0)].index
        if len(usable) == 0:
            raise ValueError(f"No variable reference signals for {service}")
        deviations = (frame[usable] - reference[usable].median()).abs() / scale[usable]
        scores[service] = deviations.median(axis=1, skipna=False)
    return scores


def rank_services(scores, thresholds):
    rows = []
    for (run, scenario), group in scores.groupby(level=["run", "test"]):
        timed = group.droplevel(["run", "test"]).asfreq("s")
        for service in SERVICES:
            series = timed[service]
            available = series.notna()
            flagged = available & series.gt(thresholds[service])
            persistent = flagged.rolling(PERSISTENCE).sum().eq(PERSISTENCE)
            onset = np.nan
            if persistent.any():
                onset = (persistent[persistent].index[0] - timed.index[0]).total_seconds()
                onset -= PERSISTENCE - 1
            rows.append({
                "run": run, "test": scenario, "service": service,
                "observations": int(available.sum()),
                "fraction_above_reference": flagged.sum() / available.sum() if available.any() else np.nan,
                "median_score": series.median(), "onset_seconds": onset,
            })
    rankings = pd.DataFrame(rows).sort_values(
        ["run", "test", "fraction_above_reference", "onset_seconds", "service"],
        ascending=[True, True, False, True, True],
    )
    rankings["rank"] = rankings.groupby(["run", "test"]).cumcount() + 1
    return rankings


def lag_associations(example):
    rows = []
    for first, second in combinations(SERVICES, 2):
        for lag in range(-MAX_LAG, MAX_LAG + 1):
            pair = pd.concat([example[first], example[second].shift(-lag)], axis=1).dropna()
            if len(pair) < 20 or pair.nunique().min() < 2:
                continue
            rows.append({
                "first_service": first, "second_service": second, "lag_seconds": lag,
                "paired_seconds": len(pair), "spearman": pair.corr(method="spearman").iat[0, 1],
            })
    table = pd.DataFrame(rows, columns=[
        "first_service", "second_service", "lag_seconds", "paired_seconds", "spearman",
    ])
    return table.sort_values("spearman", key=lambda values: values.abs(), ascending=False)


def main():
    split = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))["runs"]
    aligned = pd.read_parquet(OUTPUT / "aligned_metrics.parquet").set_index(KEYS).sort_index()
    run = aligned.index.get_level_values("run")
    normal = run.isin(split["train"]) & (aligned.index.get_level_values("test") == "correct")
    relevant = normal | run.isin(split["test"])
    scores = service_scores(aligned.loc[relevant], aligned.loc[normal])
    thresholds = scores.loc[aligned.index[normal]].quantile(0.95)
    test = scores.loc[scores.index.get_level_values("run").isin(split["test"])]
    rankings = rank_services(test, thresholds)
    example_run = sorted(split["test"])[0]
    example = test.xs((example_run, EXAMPLE)).asfreq("s")
    example.index = (example.index - example.index[0]).total_seconds()
    example.index.name = "elapsed_seconds"
    associations = lag_associations(example)
    RESULTS.mkdir(exist_ok=True)
    rankings.to_csv(RESULTS / "rca_rankings.csv", index=False)
    associations.to_csv(RESULTS / "rca_lag_associations.csv", index=False)
    example.div(thresholds.where(thresholds.gt(0))).to_csv(RESULTS / "rca_example_scores.csv")
    summary = {
        "example_run": example_run, "example_scenario": EXAMPLE,
        "runs": sorted(split["test"]), "thresholds": thresholds.to_dict(),
        "scenario_pairs": int(rankings[["run", "test"]].drop_duplicates().shape[0]),
        "service_rankings": len(rankings),
    }
    (RESULTS / "rca_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(rankings[(rankings.run == example_run) & (rankings.test == EXAMPLE)].to_string(index=False))
    print(associations.head(3).to_string(index=False))


if __name__ == "__main__":
    main()
