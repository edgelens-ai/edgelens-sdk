# Weights & Biases example — streaming + sweeps

Three patterns: final stats per run, streaming snapshots during a
soak test, and W&B Sweeps for hyperparameter exploration.

## Setup

```bash
cd examples/wandb
pip install -r requirements.txt
wandb login
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
export WANDB_PROJECT=face-detector-perf
```

## Run

```bash
# Final-stats run
python bench_final.py --model ./models/face_v3.2.1.cvimodel

# Streaming soak — watch the line chart update live
python bench_streaming.py --duration-min 60

# W&B Sweep — Bayesian search over confidence_threshold + nms_iou
wandb sweep sweep.yaml
wandb agent <SWEEP_ID> --count 20
```

## What it logs

| File | Pattern |
|---|---|
| `bench_final.py` | One run, final stats (`fps/avg`, `latency_ms/p95`, etc.). Best for CI gates. |
| `bench_streaming.py` | One run, one `wandb.log({...})` per minute over the duration. Best for catching drift. |
| `sweep.yaml` + `bench_sweep.py` | Bayesian sweep maximizing `fps/avg`. Best for finding good config under real-hardware constraints. |

## Files

```
examples/wandb/
├── README.md
├── requirements.txt
├── bench_final.py
├── bench_streaming.py
├── bench_sweep.py
├── sweep.yaml
└── models/
    └── README.md
```
