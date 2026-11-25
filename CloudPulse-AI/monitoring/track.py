"""Track an evaluated checkpoint and create a version in the local MLflow registry."""

import hashlib
import json
from pathlib import Path

import mlflow
from mlflow import MlflowClient


def main():
    root = Path("results/mlflow").resolve()
    root.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri("sqlite:///" + (root / "tracking.sqlite").as_posix())
    client = MlflowClient()
    experiment = "CloudPulse AI"
    if client.get_experiment_by_name(experiment) is None:
        client.create_experiment(experiment, artifact_location=(root / "artifacts").as_uri())
    mlflow.set_experiment(experiment)
    checkpoint = Path("models/dense_autoencoder.pt")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    evaluation = json.loads(Path("results/dense_autoencoder_metrics.json").read_text())
    name = "cloudpulse-dense-autoencoder"
    for version in client.search_model_versions(f"name = '{name}'"):
        if version.tags.get("sha256") == digest:
            print(f"{name} version {version.version} already tracks {digest[:12]}")
            return

    with mlflow.start_run(run_name="Dense autoencoder") as run:
        mlflow.log_params({"device": evaluation["device"], "checkpoint_sha256": digest,
                           "best_epoch": evaluation["best_epoch"]})
        mlflow.log_metrics({key: value for key, value in evaluation.items() if isinstance(value, (int, float))})
        mlflow.log_artifact(str(checkpoint), "model")
        mlflow.log_artifact("results/dense_autoencoder_history.csv", "evaluation")
        mlflow.log_artifact("data/processed/preprocessing.json", "preprocessing")
        try:
            client.get_registered_model(name)
        except mlflow.exceptions.MlflowException as error:
            if error.error_code != "RESOURCE_DOES_NOT_EXIST":
                raise
            client.create_registered_model(name)
        source = client.download_artifacts(run.info.run_id, f"model/{checkpoint.name}")
        version = client.create_model_version(name, Path(source).resolve().as_uri(), run.info.run_id,
                                              tags={"sha256": digest})
    print(f"{name} version {version.version}, run {run.info.run_id}")


if __name__ == "__main__":
    main()
