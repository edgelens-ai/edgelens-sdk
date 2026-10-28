"""Soak test — one wandb.log per minute over a long duration.

The W&B dashboard shows fps + latency drifting (or not) over the hour
— useful for catching thermal throttling, memory leaks, model state
degradation, anything that takes minutes to manifest.
"""

from __future__ import annotations

import argparse
import time

import wandb

from edgelens import EdgeLensClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--duration-min", type=int, default=60)
    ap.add_argument("--snapshot-every-s", type=int, default=60)
    args = ap.parse_args()

    run = wandb.init(
        config={
            "model": args.model,
            "duration_min": args.duration_min,
            "snapshot_every_s": args.snapshot_every_s,
        },
    )

    client = EdgeLensClient()
    with client.create_session(
        device_type="recamera-2002", os="stock-os"
    ) as session:
        session.wait_ready()
        wandb.config.update({"session_id": session.id})

        session.device.deploy(model=args.model)
        session.device.inference.start()

        snapshots = args.duration_min * 60 // args.snapshot_every_s
        for step in range(snapshots):
            time.sleep(args.snapshot_every_s)
            s = session.device.inference.stats()
            wandb.log({
                "fps": s.fps.avg,
                "latency_ms_p95": s.latency_ms.p95,
                "latency_ms_p99": s.latency_ms.p99,
                "step_minute": step * args.snapshot_every_s // 60,
            })

        session.device.inference.stop()

    run.finish()


if __name__ == "__main__":
    main()
