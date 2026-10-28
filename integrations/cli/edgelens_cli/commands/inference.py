"""``edgelens inference`` subcommands."""

from __future__ import annotations

from typing import Optional

import click
from edgelens.errors import EdgeLensError

from edgelens_cli.commands.device import _session_with_device
from edgelens_cli.output import emit, error


@click.group(name="inference")
def inference_group() -> None:
    """Control on-device inference (stock OS only)."""


@inference_group.command("start")
@click.option("--session", "session_id", default=None)
@click.pass_context
def inference_start(ctx: click.Context, session_id: Optional[str]) -> None:
    session = _session_with_device(ctx, session_id)
    try:
        session.device.inference.start()
    except EdgeLensError as e:
        error(str(e))
    emit({"action": "start"}, json_mode=ctx.obj["json_mode"], human="✓ inference started")


@inference_group.command("stop")
@click.option("--session", "session_id", default=None)
@click.pass_context
def inference_stop(ctx: click.Context, session_id: Optional[str]) -> None:
    session = _session_with_device(ctx, session_id)
    try:
        session.device.inference.stop()
    except EdgeLensError as e:
        error(str(e))
    emit({"action": "stop"}, json_mode=ctx.obj["json_mode"], human="✓ inference stopped")


@inference_group.command("once")
@click.option("--session", "session_id", default=None)
@click.pass_context
def inference_once(ctx: click.Context, session_id: Optional[str]) -> None:
    """Run a single frame and print the detections."""
    session = _session_with_device(ctx, session_id)
    try:
        result = session.device.inference.once()
    except EdgeLensError as e:
        error(str(e))
    emit(
        result,
        json_mode=ctx.obj["json_mode"],
        human=f"detections: {len(result.get('detections', []))}",
    )


@inference_group.command("stats")
@click.option("--session", "session_id", default=None)
@click.pass_context
def inference_stats(ctx: click.Context, session_id: Optional[str]) -> None:
    """Print a point-in-time inference snapshot."""
    session = _session_with_device(ctx, session_id)
    try:
        snap = session.device.inference.snapshot()
    except EdgeLensError as e:
        error(str(e))
    payload = snap.model_dump() if hasattr(snap, "model_dump") else snap
    human = (
        f"fps:        {snap.fps}\n"
        f"latency_ms: {snap.latency_ms}\n"
        f"detections: {snap.detection_count}"
    )
    emit(payload, json_mode=ctx.obj["json_mode"], human=human)


@inference_group.command("run")
@click.option("--duration", default=30.0, type=float, help="Seconds to run.")
@click.option("--collect-frames", is_flag=True, default=False)
@click.option("--session", "session_id", default=None)
@click.pass_context
def inference_run(
    ctx: click.Context, duration: float, collect_frames: bool, session_id: Optional[str]
) -> None:
    """Run inference for a duration and print aggregated stats."""
    session = _session_with_device(ctx, session_id)
    try:
        stats = session.device.inference.run(duration=duration, collect_frames=collect_frames)
    except EdgeLensError as e:
        error(str(e))
    payload = stats.model_dump() if hasattr(stats, "model_dump") else stats
    human = (
        f"duration_s:   {stats.duration_s}\n"
        f"total_frames: {stats.total_frames}\n"
        f"fps avg:      {stats.fps.avg:.2f}  p95: {stats.fps.p95:.2f}\n"
        f"latency p95:  {stats.latency_ms.p95:.2f}ms"
    )
    emit(payload, json_mode=ctx.obj["json_mode"], human=human)
