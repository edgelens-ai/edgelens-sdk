# MLflow example — model perf comparison

Logs face-detector inference runs to MLflow so you can compare model
versions in the MLflow UI.

## Setup

```bash
cd examples/mlflow
pip install -r requirements.txt
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx

# MLflow tracking URI — local file store by default. Override for a
# tracking server:
# export MLFLOW_TRACKING_URI=https://mlflow.internal.corp
```

## Run

```bash
# Single run
python bench_single.py --model ./models/face_v3.2.1.cvimodel

# Sweep multiple model versions as nested children of one parent run
python bench_sweep.py

# Then open the UI
mlflow ui --port 5000
```

## What it logs

| File | Run shape |
|---|---|
| `bench_single.py` | One MLflow run per invocation. Params: `model_version`, `os`, `session_id`. Metrics: `fps_{avg,p50,p95}`, `latency_ms_{avg,p95,p99}`, `detection_count`. |
| `bench_sweep.py` | Parent run wrapping N child runs, one per model version. Lets you sort children by `fps_avg` in the UI. |

## Files

```
examples/mlflow/
├── README.md
├── requirements.txt
├── bench_single.py
├── bench_sweep.py
└── models/
    └── README.md
```
