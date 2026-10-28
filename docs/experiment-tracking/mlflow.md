# MLflow

EdgeLens isn't an MLflow plugin — the SDK returns plain Python objects
that drop straight into MLflow's `log_metric` / `log_param` /
`log_artifact` calls. Two patterns work well.

## Pattern 1 — log each session as a run

```python
import mlflow
from edgelens import EdgeLensClient

mlflow.set_experiment("face-detector-perf")
client = EdgeLensClient()

with mlflow.start_run() as run:
    mlflow.log_param("model_version", "v3.2.1")
    mlflow.log_param("os", "stock-os")
    mlflow.log_param("device_type", "recamera-2002")

    with client.create_session(device_type="recamera-2002", os="stock-os") as session:
        session.wait_ready()
        mlflow.log_param("session_id", session.id)

        session.device.deploy(model="./models/face_v3.2.1.cvimodel")
        stats = session.device.inference.run(duration=60)

        mlflow.log_metric("fps_avg", stats.fps.avg)
        mlflow.log_metric("fps_p50", stats.fps.p50)
        mlflow.log_metric("fps_p95", stats.fps.p95)
        mlflow.log_metric("latency_ms_avg", stats.latency_ms.avg)
        mlflow.log_metric("latency_ms_p95", stats.latency_ms.p95)
        mlflow.log_metric("latency_ms_p99", stats.latency_ms.p99)
        mlflow.log_metric("detection_count", stats.detection_count)
```

Now every time you change the model and re-run, MLflow keeps the
comparison: fps and latency per model version, side-by-side in the UI.

## Pattern 2 — parameter sweep with one parent + per-model child runs

```python
MODELS = [
    ("v3.0.0", "./models/face_v3.0.0.cvimodel"),
    ("v3.1.0", "./models/face_v3.1.0.cvimodel"),
    ("v3.2.1", "./models/face_v3.2.1.cvimodel"),
]

with mlflow.start_run(run_name="face_detector_sweep"):
    for version, path in MODELS:
        with mlflow.start_run(run_name=version, nested=True):
            mlflow.log_param("model_version", version)

            with client.create_session(device_type="recamera-2002", os="stock-os") as s:
                s.wait_ready()
                s.device.deploy(model=path)
                stats = s.device.inference.run(duration=60)

                mlflow.log_metric("fps_avg", stats.fps.avg)
                mlflow.log_metric("latency_ms_p95", stats.latency_ms.p95)
```

MLflow's UI lets you sort the nested children by `fps_avg` to see
which version is fastest.

## Logging the model artifact alongside the metric

If the `.cvimodel` is the artifact you want to associate with the run:

```python
mlflow.log_artifact("./models/face_v3.2.1.cvimodel", artifact_path="model")
```

This puts a copy in MLflow's artifact store keyed by run id. Useful
for "what model was actually deployed to get these numbers".

## CI: gating a PR on MLflow comparison

Combine with [GitHub Actions](../ci-cd/github-actions.md): run the
benchmark in CI, log to MLflow, then compare to the parent run via
`mlflow.search_runs(...)`. The pattern is essentially "fail the
build if `fps_avg` regressed > 5% from main".

## Example project

Full working project: [`examples/mlflow/`](../../examples/mlflow/).
