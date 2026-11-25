"""Train and evaluate a dense normal-reference autoencoder."""

import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    auc, average_precision_score, balanced_accuracy_score, confusion_matrix,
    precision_recall_curve, precision_recall_fscore_support, roc_auc_score, roc_curve,
)
from torch import nn

from src.preprocess import OUTPUT, SEED

EPOCHS = 100
BATCH_SIZE = 16
LEARNING_RATE = 0.001
HIDDEN = 32
LATENT = 8


def build_autoencoder(width):
    return nn.Sequential(
        nn.Linear(width, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, LATENT),
        nn.Linear(LATENT, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, width),
    )


@torch.inference_mode()
def score(model, inputs):
    return (model(inputs) - inputs).square().mean(dim=1)


def train_autoencoder(train_normal, validation_normal):
    model = build_autoencoder(train_normal.shape[1]).to(train_normal.device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    best_loss = float("inf")
    history = []
    for epoch in range(1, EPOCHS + 1):
        model.train()
        for indices in torch.randperm(len(train_normal)).split(BATCH_SIZE):
            batch = train_normal[indices.to(train_normal.device)]
            optimizer.zero_grad()
            loss = (model(batch) - batch).square().mean()
            loss.backward()
            optimizer.step()

        model.eval()
        train_loss = score(model, train_normal).mean().item()
        validation_loss = score(model, validation_normal).mean().item()
        history.append((epoch, train_loss, validation_loss))
        if validation_loss < best_loss:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    return model, best_epoch, pd.DataFrame(history, columns=["epoch", "train_mse", "validation_mse"])


def main():
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    prep = json.loads((OUTPUT / "preprocessing.json").read_text(encoding="utf-8"))
    features = prep["feature_columns"]

    def load(split):
        table = pd.read_parquet(OUTPUT / f"windows_{split}.parquet")
        truth = table.error.to_numpy()
        inputs = torch.as_tensor(table[features].to_numpy().astype(np.float32), device=device)
        return truth, inputs

    train_truth, train = load("train")
    validation_truth, validation = load("validation")
    test_truth, test = load("test")
    train_normal = train[torch.as_tensor(~train_truth, device=device)]
    validation_normal = validation[torch.as_tensor(~validation_truth, device=device)]
    if min(len(train_normal), len(validation_normal)) == 0:
        raise ValueError("Training and validation must contain normal windows")

    start = perf_counter()
    model, best_epoch, history = train_autoencoder(train_normal, validation_normal)
    training_seconds = perf_counter() - start
    validation_scores = score(model, validation).cpu().numpy()
    fpr, tpr, thresholds = roc_curve(validation_truth, validation_scores)
    finite = np.isfinite(thresholds)
    threshold = float(thresholds[finite][np.argmax((tpr - fpr)[finite])])

    score(model, test)
    if device.type == "cuda":
        torch.cuda.synchronize()
    timings = []
    for _ in range(10):
        start = perf_counter()
        scores = score(model, test).cpu().numpy()
        timings.append(perf_counter() - start)

    prediction = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(test_truth, prediction, labels=[False, True]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(
        test_truth, prediction, average="binary", zero_division=0,
    )
    curve_precision, curve_recall, _ = precision_recall_curve(test_truth, scores)
    metrics = {
        "device": str(device), "torch_version": str(torch.__version__), "best_epoch": best_epoch,
        "training_normal_windows": len(train_normal), "validation_normal_windows": len(validation_normal),
        "threshold": threshold, "training_seconds": training_seconds,
        "inference_median_seconds": float(np.median(timings)),
        "test_windows": len(test_truth), "roc_auc": roc_auc_score(test_truth, scores),
        "pr_auc": auc(curve_recall, curve_precision),
        "average_precision": average_precision_score(test_truth, scores),
        "precision": precision, "recall": recall, "f1": f1,
        "balanced_accuracy": balanced_accuracy_score(test_truth, prediction),
        "false_positive_rate": fp / (fp + tn),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }
    results = Path("results")
    models = Path("models")
    results.mkdir(exist_ok=True)
    models.mkdir(exist_ok=True)
    torch.save({
        "state_dict": {key: value.cpu() for key, value in model.state_dict().items()},
        "feature_columns": features, "threshold": threshold, "hidden": HIDDEN, "latent": LATENT,
        "scaler_mean": prep["scaler_mean"], "scaler_scale": prep["scaler_scale"],
        "window_seconds": prep["window_seconds"], "stride_seconds": prep["stride_seconds"],
    }, models / "dense_autoencoder.pt")
    history.to_csv(results / "dense_autoencoder_history.csv", index=False)
    (results / "dense_autoencoder_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
