# Weights & Biases

Like MLflow, W&B isn't an EdgeLens integration — EdgeLens returns
plain objects, you `wandb.log()` them. The W&B-specific value is
real-time streaming: `device.inference.stats()` can be polled inside
a session and each snapshot is one `wandb.log({...})` call.

## Pattern 1 — final stats per run

```python
import wandb
from edgelens import EdgeLensClient

client = EdgeLensClient()

run = wandb.init(
    project="face-detector-perf",
    config={
        "model_version": "v3.2.1",
        "os": "stock-os",
        "device_type": "recamera-2002",
    },
)

with client.create_session(device_type="recamera-2002", os="stock-os") as session:
    session.wait_ready()
    wandb.config.update({"session_id": session.id})

    session.device.deploy(model="./models/face_v3.2.1.cvimodel")
    stats = session.device.inference.run(duration=60)

    wandb.log({
        "fps/avg": stats.fps.avg,
        "fps/p95": stats.fps.p95,
        "latency_ms/avg": stats.latency_ms.avg,
        "latency_ms/p95": stats.latency_ms.p95,
        "latency_ms/p99": stats.latency_ms.p99,
        "detection_count": stats.detection_count,
    })

run.finish()
```

## Pattern 2 — streaming snapshots during a soak test

The thing W&B is uniquely good at — watch the line chart update live:

```python
import time
import wandb
from edgelens import EdgeLensClient

client = EdgeLensClient()
run = wandb.init(project="face-detector-soak")

with client.create_session(device_type="recamera-2002", os="stock-os") as session:
    session.wait_ready()
    session.device.deploy(model="./models/face_v3.2.1.cvimodel")
    session.device.inference.start()

    for step in range(60):  # 60 minutes of one-snapshot-per-minute
        time.sleep(60)
        s = session.device.inference.stats()
        wandb.log({
            "fps": s.fps.avg,
            "latency_ms_p95": s.latency_ms.p95,
            "step_minute": step,
        })

    session.device.inference.stop()

run.finish()
```

The W&B dashboard shows fps and latency drifting (or not) over the
hour — useful for catching thermal throttling, memory leaks, model
state degradation, anything that takes minutes to manifest.

## Sweeps

W&B Sweeps are a natural fit for hyperparameter exploration that ends
on real-hardware metrics:

```yaml
# sweep.yaml
method: bayes
metric:
  name: fps/avg
  goal: maximize
parameters:
  confidence_threshold:
    min: 0.3
    max: 0.9
  nms_iou:
    min: 0.3
    max: 0.7
```

```python
import wandb
from edgelens import EdgeLensClient

def train():
    run = wandb.init()
    config = wandb.config

    with EdgeLensClient().create_session(
        device_type="recamera-2002", os="stock-os"
    ) as session:
        session.wait_ready()
        session.device.deploy(
            model="./models/face_v3.2.1.cvimodel",
            config={
                "confidence_threshold": config.confidence_threshold,
                "nms_iou": config.nms_iou,
            },
        )
        stats = session.device.inference.run(duration=30)
        wandb.log({"fps/avg": stats.fps.avg, "latency_ms/p95": stats.latency_ms.p95})

wandb.agent(sweep_id, function=train, count=20)
```

Note: each agent call allocates a session. Watch the key's
`max_concurrent_sessions`: portal-minted keys allow one concurrent
session, and the portal has no control to change that yet. Size the
agent fanout to the key's cap, or run the sweep with `count=N` instead of relying on
infinite agents.

## Example project

Full working project: [`examples/wandb/`](../../examples/wandb/).
