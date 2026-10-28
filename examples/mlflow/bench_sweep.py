"""Sweep multiple model versions, log each as a nested MLflow run.

After running, sort the nested children by ``fps_avg`` in the MLflow UI
to see which version is fastest.
"""

from __future__ import annotations

import mlflow

from edgelens import EdgeLensClient


MODELS = [
    ("v3.0.0", "./models/face_v3.0.0.cvimodel"),
    ("v3.1.0", "./models/face_v3.1.0.cvimodel"),
    ("v3.2.1", "./models/face_v3.2.1.cvimodel"),
]


def main() -> None:
    mlflow.set_experiment("face-detector-sweep")
    client = EdgeLensClient()

    with mlflow.start_run(run_name="face_detector_sweep"):
        for version, path in MODELS:
            with mlflow.start_run(run_name=version, nested=True):
                mlflow.log_param("model_version", version)
                mlflow.log_param("os", "stock-os")

                with client.create_session(
                    device_type="recamera-2002", os="stock-os"
                ) as session:
                    session.wait_ready()
                    mlflow.log_param("session_id", session.id)

                    session.device.deploy(model=path)
                    stats = session.device.inference.run(duration=60)

                    mlflow.log_metric("fps_avg", stats.fps.avg)
                    mlflow.log_metric("fps_p95", stats.fps.p95)
                    mlflow.log_metric("latency_ms_avg", stats.latency_ms.avg)
                    mlflow.log_metric("latency_ms_p95", stats.latency_ms.p95)
                    mlflow.log_metric("latency_ms_p99", stats.latency_ms.p99)

                print(f"  logged {version}: fps_avg={stats.fps.avg:.1f}")


if __name__ == "__main__":
    main()
