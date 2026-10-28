"""Log one final stats snapshot per run. Best fit for CI gates."""

from __future__ import annotations

import argparse

import wandb

from edgelens import EdgeLensClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--model-version", required=True)
    ap.add_argument("--duration", type=int, default=60)
    args = ap.parse_args()

    run = wandb.init(
        config={
            "model_version": args.model_version,
            "os": "stock-os",
            "device_type": "recamera-2002",
            "duration_s": args.duration,
        },
    )

    client = EdgeLensClient()
    with client.create_session(
        device_type="recamera-2002", os="stock-os"
    ) as session:
        session.wait_ready()
        wandb.config.update({"session_id": session.id})

        session.device.deploy(model=args.model)
        stats = session.device.inference.run(duration=args.duration)

        wandb.log({
            "fps/avg": stats.fps.avg,
            "fps/p50": stats.fps.p50,
            "fps/p95": stats.fps.p95,
            "latency_ms/avg": stats.latency_ms.avg,
            "latency_ms/p95": stats.latency_ms.p95,
            "latency_ms/p99": stats.latency_ms.p99,
            "detection_count": stats.detection_count,
        })

    run.finish()


if __name__ == "__main__":
    main()
