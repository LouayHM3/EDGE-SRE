"""Compare temporal detectors on the same LO2v2 windows as the dense baseline."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    auc, balanced_accuracy_score, confusion_matrix, precision_recall_curve,
    precision_recall_fscore_support, roc_auc_score, roc_curve,
)
from torch import nn

from src.deep_learning import BATCH_SIZE, EPOCHS, LEARNING_RATE
from src.preprocess import OUTPUT, SEED


class Recurrent(nn.Module):
    def __init__(self, width, reconstruct=False):
        super().__init__()
        self.encoder = nn.LSTM(width, 24, batch_first=True)
        self.decoder = nn.LSTM(24, 24, batch_first=True) if reconstruct else None
        self.output = nn.Linear(24, width)

    def forward(self, x):
        encoded, _ = self.encoder(x)
        state = encoded[:, -1]
        if self.decoder is None:
            return self.output(state)
        decoded, _ = self.decoder(state.unsqueeze(1).expand(-1, x.shape[1], -1))
        return self.output(decoded)


class TemporalConv(nn.Module):
    def __init__(self, width):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv1d(width, 24, 3, dilation=1), nn.ReLU(),
            nn.Conv1d(24, 24, 3, dilation=2), nn.ReLU(),
            nn.Conv1d(24, 24, 3, dilation=4), nn.ReLU(),
        )
        self.output = nn.Linear(24, width)

    def forward(self, x):
        return self.output(self.layers(x.transpose(1, 2))[:, :, -1])


class Attention(nn.Module):
    def __init__(self, width, history):
        super().__init__()
        self.project = nn.Linear(width, 24)
        self.position = nn.Parameter(torch.zeros(1, history, 24))
        self.encoder = nn.TransformerEncoderLayer(24, 4, 48, batch_first=True, dropout=0)
        self.output = nn.Linear(24, width)

    def forward(self, x):
        encoded = self.encoder(self.project(x) + self.position)
        return self.output(encoded[:, -1])


def split_sequences():
    aligned = pd.read_parquet(OUTPUT / "aligned_metrics.parquet")
    keys = ["run", "test", "timestamp"]
    columns = [column for column in aligned if column not in keys]
    by_test = {
        key: group.set_index("timestamp")[columns]
        for key, group in aligned.groupby(["run", "test"])
    }
    metadata = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    splits = {}
    for split in ("train", "validation", "test"):
        table = pd.read_parquet(OUTPUT / f"windows_{split}.parquet")
        sequences = []
        for row in table.itertuples(index=False):
            grid = pd.date_range(row.window_start, row.window_end, freq="s")
            sequences.append(by_test[row.run, row.test].reindex(grid).to_numpy())
        values = np.stack(sequences)
        if not np.isfinite(values).all() or values.shape[1] != metadata["window_seconds"]:
            raise ValueError(f"Unexpected sequence data in {split}")
        splits[split] = values, table.error.to_numpy()
    return splits, columns


def errors(model, batch, reconstruct):
    inputs, target = (batch, batch) if reconstruct else (batch[:, :-1], batch[:, -1])
    squared = (model(inputs) - target).square()
    return squared.flatten(1).mean(dim=1)


def evaluate(name, model, reconstruct, train, validation, test, val_truth, test_truth):
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    normal_val = validation[torch.as_tensor(~val_truth, device=validation.device)]
    best = float("inf")
    start = perf_counter()
    for epoch in range(1, EPOCHS + 1):
        model.train()
        for indices in torch.randperm(len(train)).split(BATCH_SIZE):
            optimizer.zero_grad()
            errors(model, train[indices.to(train.device)], reconstruct).mean().backward()
            optimizer.step()
        model.eval()
        with torch.inference_mode():
            loss = errors(model, normal_val, reconstruct).mean().item()
        if loss < best:
            best, best_epoch = loss, epoch
            state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
    model.load_state_dict(state)
    with torch.inference_mode():
        val = errors(model, validation, reconstruct).cpu().numpy()
        fpr, tpr, thresholds = roc_curve(val_truth, val)
        finite = np.isfinite(thresholds)
        threshold = float(thresholds[finite][np.argmax((tpr - fpr)[finite])])
        train_seconds = perf_counter() - start
        errors(model, test, reconstruct).cpu()
        timings = []
        for _ in range(10):
            start = perf_counter()
            scores = errors(model, test, reconstruct).cpu().numpy()
            timings.append(perf_counter() - start)
    predicted = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(test_truth, predicted, labels=[False, True]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(
        test_truth, predicted, average="binary", zero_division=0,
    )
    p, r, _ = precision_recall_curve(test_truth, scores)
    row = {
        "model": name, "best_epoch": best_epoch, "threshold": threshold,
        "roc_auc": roc_auc_score(test_truth, scores),
        "pr_auc": auc(r, p), "precision": precision, "recall": recall, "f1": f1,
        "balanced_accuracy": balanced_accuracy_score(test_truth, predicted),
        "false_positive_rate": fp / (tn + fp), "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        "train_seconds": train_seconds, "inference_median_seconds": np.median(timings),
    }
    return row, state


def main():
    torch.set_num_threads(2)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    splits, columns = split_sequences()
    train, train_truth = splits["train"]
    train = train[~train_truth]
    if not len(train) or splits["validation"][1].all():
        raise ValueError("Training and validation must contain normal windows")
    mean = train.mean(axis=(0, 1))
    scale = train.std(axis=(0, 1))
    scale[scale == 0] = 1

    def tensor(values):
        return torch.as_tensor((values - mean) / scale, dtype=torch.float32, device=device)

    x_train = tensor(train)
    validation, val_truth = splits["validation"]
    test, test_truth = splits["test"]
    x_val, x_test = tensor(validation), tensor(test)
    width = len(columns)
    models = {
        "lstm_forecast": lambda: Recurrent(width),
        "lstm_autoencoder": lambda: Recurrent(width, reconstruct=True),
        "tcn_forecast": lambda: TemporalConv(width),
        "transformer_forecast": lambda: Attention(width, x_train.shape[1] - 1),
    }
    results = []
    model_dir, result_dir = Path("models"), Path("results")
    model_dir.mkdir(exist_ok=True)
    result_dir.mkdir(exist_ok=True)
    for name, build in models.items():
        torch.manual_seed(SEED)
        row, weights = evaluate(
            name, build().to(device), name == "lstm_autoencoder",
            x_train, x_val, x_test, val_truth, test_truth,
        )
        torch.save({
            "state_dict": weights, "model": name, "feature_columns": columns,
            "scaler_mean": mean.tolist(), "scaler_scale": scale.tolist(),
            "threshold": row["threshold"], "window_seconds": x_train.shape[1],
        }, model_dir / f"{name}.pt")
        results.append(row)
        print(f"{name}: ROC AUC {row['roc_auc']:.3f}", flush=True)
    pd.DataFrame(results).to_csv(result_dir / "temporal_model_metrics.csv", index=False)


if __name__ == "__main__":
    main()
