"""Evaluate template, Transformer, metrics and multimodal log baselines."""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, balanced_accuracy_score, roc_auc_score
from torch import nn

from src.log_sample import CACHE, SEQUENCE_LENGTH
from src.preprocess import OUTPUT, SEED

RESULTS = Path("results")
EPOCHS = 40


class LogTransformer(nn.Module):
    def __init__(self, vocabulary_size):
        super().__init__()
        self.embedding = nn.Embedding(vocabulary_size, 24)
        self.position = nn.Parameter(torch.zeros(1, SEQUENCE_LENGTH, 24))
        self.encoder = nn.TransformerEncoderLayer(24, 4, 48, batch_first=True, dropout=0.1)
        self.output = nn.Linear(24, 1)

    def forward(self, tokens):
        hidden = self.encoder(self.embedding(tokens) + self.position)
        return self.output(hidden.mean(dim=1)).squeeze(1)


def transformer_scores(train, validation, test):
    vocabulary = {
        token: index for index, token in enumerate(
            sorted({token for sequence in train.templates for token in sequence}), start=1,
        )
    }

    def encode(table):
        return torch.tensor([[vocabulary.get(token, 0) for token in seq] for seq in table.templates])

    def target(table):
        return torch.tensor(table.error.to_numpy(), dtype=torch.float32)

    x_train, x_val, x_test = map(encode, (train, validation, test))
    y_train, y_val = target(train), target(validation)
    model = LogTransformer(len(vocabulary) + 1)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=(1 - y_train).sum() / y_train.sum())
    best = float("inf")
    for _ in range(EPOCHS):
        model.train()
        for indices in torch.randperm(len(train)).split(8):
            optimizer.zero_grad()
            loss_fn(model(x_train[indices]), y_train[indices]).backward()
            optimizer.step()
        model.eval()
        with torch.inference_mode():
            loss = loss_fn(model(x_val), y_val).item()
        if loss < best:
            best = loss
            state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    model.load_state_dict(state)
    with torch.inference_mode():
        return model(x_test).sigmoid().numpy(), len(vocabulary)


def load_splits():
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    logs = pd.DataFrame(data["documents"])
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    features = metadata["feature_columns"]
    splits = []
    for split, runs in metadata["runs"].items():
        windows = pd.read_parquet(OUTPUT / f"windows_{split}.parquet")
        pruned = windows.groupby(["run", "test"], as_index=False)[features].median()
        subset = logs[logs.run.isin(runs)]
        joined = subset.merge(pruned, on=["run", "test"], validate="one_to_one")
        if len(joined) != len(subset):
            raise ValueError(f"Logs and metric windows failed to match in {split}")
        joined["error"] = joined.test.ne("correct")
        splits.append(joined)
    return splits, features, data["compressed_bytes"]


def main():
    torch.set_num_threads(2)
    torch.manual_seed(SEED)
    (train, validation, test), features, compressed_bytes = load_splits()
    corpus = lambda table: table.templates.map(" ".join)
    vectorizer = TfidfVectorizer(token_pattern=r"\S+")
    x_train = vectorizer.fit_transform(corpus(train))
    templates = LogisticRegression(class_weight="balanced").fit(x_train, train.error)
    log_scores = templates.predict_proba(vectorizer.transform(corpus(test)))[:, 1]

    transformer, vocabulary_size = transformer_scores(train, validation, test)
    metrics = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=SEED)
    metrics.fit(train[features], train.error)
    metric_scores = metrics.predict_proba(test[features])[:, 1]
    scores = {
        "Log templates": log_scores,
        "Log Transformer": transformer,
        "Metrics Random Forest": metric_scores,
        "Late fusion": (log_scores + metric_scores) / 2,
    }
    evaluation = [{
        "model": name,
        "roc_auc": roc_auc_score(test.error, score),
        "average_precision": average_precision_score(test.error, score),
        "balanced_accuracy_at_0_5": balanced_accuracy_score(test.error, score >= 0.5),
    } for name, score in scores.items()]
    output = pd.DataFrame(evaluation)
    summary = {
        "compressed_member_bytes": compressed_bytes,
        "events_per_document": SEQUENCE_LENGTH,
        "documents_by_split": dict(zip(("train", "validation", "test"), map(len, (train, validation, test)))),
        "train_vocabulary_size": vocabulary_size,
        "train_most_common_template_counts": [count for _, count in Counter(
            token for sequence in train.templates for token in sequence
        ).most_common(5)],
        "test_error_prevalence": test.error.mean(),
        "test_runs": test.run.nunique(),
    }
    RESULTS.mkdir(exist_ok=True)
    output.to_csv(RESULTS / "log_model_metrics.csv", index=False)
    predictions = test[["run", "test", "error"]].assign(**scores)
    predictions.to_csv(RESULTS / "log_predictions.csv", index=False)
    (RESULTS / "log_sample_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(output.to_string(index=False))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
