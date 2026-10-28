"""Run one benchmark, log to MLflow as a single run."""

from __future__ import annotations

import argparse
import os

import mlflow

from edgelens import EdgeLensClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Path to .cvimodel.")
    ap.add_argument("--model-version", required=True, help="Tag for the run.")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--experiment", default="face-detector-perf")
    args = ap.parse_args()

    mlflow.set_experiment(args.experiment)
    client = EdgeLensClient()

    with mlflow.start_run() as run:
        mlflow.log_param("model_version", args.model_version)
        mlflow.log_param("os", "stock-os")
        mlflow.log_param("device_type", "recamera-2002")
        mlflow.log_param("duration_s", args.duration)

        with client.create_session(
            device_type="recamera-2002", os="stock-os"
        ) as session:
            session.wait_ready()
            mlflow.log_param("session_id", session.id)

            session.device.deploy(model=args.model)
            stats = session.device.inference.run(duration=args.duration)

            mlflow.log_metric("fps_avg", stats.fps.avg)
            mlflow.log_metric("fps_p50", stats.fps.p50)
            mlflow.log_metric("fps_p95", stats.fps.p95)
            mlflow.log_metric("latency_ms_avg", stats.latency_ms.avg)
            mlflow.log_metric("latency_ms_p95", stats.latency_ms.p95)
            mlflow.log_metric("latency_ms_p99", stats.latency_ms.p99)
            mlflow.log_metric("detection_count", stats.detection_count)

        if os.path.exists(args.model):
            mlflow.log_artifact(args.model, artifact_path="model")

        print(f"Logged run {run.info.run_id} to {args.experiment}")


if __name__ == "__main__":
    main()
