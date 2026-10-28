"""W&B Sweep target. Reads config from wandb.config — invoked by an
agent, not directly."""

from __future__ import annotations

import wandb

from edgelens import EdgeLensClient


def train() -> None:
    run = wandb.init()
    config = wandb.config

    client = EdgeLensClient()
    with client.create_session(
        device_type="recamera-2002", os="stock-os"
    ) as session:
        session.wait_ready()
        session.device.deploy(
            model="./models/face.cvimodel",
            config={
                "confidence_threshold": config.confidence_threshold,
                "nms_iou": config.nms_iou,
            },
        )
        stats = session.device.inference.run(duration=30)
        wandb.log({
            "fps/avg": stats.fps.avg,
            "latency_ms/p95": stats.latency_ms.p95,
        })

    run.finish()


if __name__ == "__main__":
    train()
