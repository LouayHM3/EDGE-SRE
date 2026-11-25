"""Evaluate anomaly detection and API error classification on fixed run splits."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    average_precision_score, balanced_accuracy_score, confusion_matrix,
    precision_recall_fscore_support, roc_auc_score, roc_curve,
)

from src.preprocess import OUTPUT, SEED

RESULTS = Path("results")
HTTP_PATTERN = r"(?:^|_)(400|401|404)(?:_|$)"


def anomaly_scores(train, validation, test, features):
    x_train, x_val, x_test = (table[features] for table in (train, validation, test))
    normal = x_train.loc[~train.error]
    center = normal.median()
    scale = (normal.quantile(0.75) - normal.quantile(0.25)).replace(0, 1)

    def deviation(x):
        return ((x - center) / scale).abs().median(axis=1).to_numpy()

    yield "Robust deviation", deviation(x_val), deviation(x_test)

    isolation = IsolationForest(n_estimators=200, random_state=SEED).fit(normal)
    yield "Isolation Forest", -isolation.score_samples(x_val), -isolation.score_samples(x_test)

    models = {
        "Logistic Regression": LogisticRegression(class_weight="balanced", max_iter=2000),
        "Random Forest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=SEED,
        ),
    }
    for name, model in models.items():
        model.fit(x_train, train.error)
        yield name, model.predict_proba(x_val)[:, 1], model.predict_proba(x_test)[:, 1]


def evaluate_detection(train, validation, test, features):
    rows = []
    for name, validation_scores, scores in anomaly_scores(train, validation, test, features):
        fpr, tpr, thresholds = roc_curve(validation.error, validation_scores)
        threshold = thresholds[np.argmax(tpr - fpr)]
        prediction = scores >= threshold
        tn, fp, fn, tp = confusion_matrix(test.error, prediction, labels=[False, True]).ravel()
        precision, recall, f1, _ = precision_recall_fscore_support(
            test.error, prediction, average="binary", zero_division=0,
        )
        rows.append({
            "model": name, "threshold": threshold, "roc_auc": roc_auc_score(test.error, scores),
            "average_precision": average_precision_score(test.error, scores),
            "balanced_accuracy": balanced_accuracy_score(test.error, prediction),
            "precision": precision, "recall": recall, "f1": f1, "false_positive_rate": fp / (fp + tn),
            "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        })
    return pd.DataFrame(rows)


def evaluate_diagnosis(train, test, features):
    train = train.loc[train.error].copy()
    test = test.loc[test.error].copy()
    outcomes = []
    for table in (train, test):
        table["http_status"] = table.test.str.extract(HTTP_PATTERN, expand=False)
        if table.http_status.isna().any():
            raise ValueError("One or more API error scenarios lack a supported HTTP code")
    for target in ("http_status", "test"):
        model = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=SEED)
        encoder = LabelEncoder().fit(train[target])
        model.fit(train[features], encoder.transform(train[target]))
        scores = model.predict_proba(test[features])
        classes = encoder.inverse_transform(model.classes_)
        ranked = classes[np.argsort(-scores, axis=1, kind="stable")[:, :3]]
        truth = test[target].to_numpy()
        majority = train[target].mode().iloc[0]
        outcomes.append({
            "target": "API error scenario" if target == "test" else "HTTP status",
            "training_classes": train[target].nunique(),
            "test_classes": test[target].nunique(),
            "test_windows": len(test),
            "majority_top1_accuracy": np.mean(truth == majority),
            "top1_accuracy": np.mean(ranked[:, 0] == truth),
            "balanced_accuracy": balanced_accuracy_score(truth, ranked[:, 0]),
            "top3_accuracy": np.mean((ranked == truth[:, None]).any(axis=1)) if target == "test" else None,
        })
    return pd.DataFrame(outcomes)


def main():
    start = perf_counter()
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    train, validation, test = (
        pd.read_parquet(OUTPUT / f"windows_{split}.parquet")
        for split in ("train", "validation", "test")
    )
    features = metadata["feature_columns"]
    detection = evaluate_detection(train, validation, test, features)
    diagnosis = evaluate_diagnosis(train, test, features)
    RESULTS.mkdir(exist_ok=True)
    detection.to_csv(RESULTS / "ml_detection.csv", index=False)
    diagnosis.to_csv(RESULTS / "ml_diagnosis.csv", index=False)
    print(detection.round(4).to_string(index=False))
    print(diagnosis.round(4).to_string(index=False))
    print(f"Evaluation finished in {perf_counter() - start:.1f} seconds.")


if __name__ == "__main__":
    main()
