"""``edgelens display`` subcommands."""

from __future__ import annotations

from typing import Optional

import click
from edgelens.errors import EdgeLensError

from edgelens_cli.commands.device import _session_with_device
from edgelens_cli.output import emit, error


@click.group(name="display")
def display_group() -> None:
    """Control the camera's external display."""


@display_group.command("play")
@click.argument("source")
@click.option("--loop/--no-loop", default=False)
@click.option("--session", "session_id", default=None)
@click.pass_context
def display_play(
    ctx: click.Context, source: str, loop: bool, session_id: Optional[str]
) -> None:
    """Play a video on the display."""
    session = _session_with_device(ctx, session_id)
    try:
        session.device.display.play(source, loop=loop)
    except EdgeLensError as e:
        error(str(e))
    emit(
        {"action": "play", "source": source, "loop": loop},
        json_mode=ctx.obj["json_mode"],
        human=f"✓ display playing {source}{' (loop)' if loop else ''}",
    )


@display_group.command("show")
@click.argument("source")
@click.option("--session", "session_id", default=None)
@click.pass_context
def display_show(ctx: click.Context, source: str, session_id: Optional[str]) -> None:
    """Show a still image on the display."""
    session = _session_with_device(ctx, session_id)
    try:
        session.device.display.show(source)
    except EdgeLensError as e:
        error(str(e))
    emit(
        {"action": "show", "source": source},
        json_mode=ctx.obj["json_mode"],
        human=f"✓ display showing {source}",
    )


@display_group.command("stop")
@click.option("--session", "session_id", default=None)
@click.pass_context
def display_stop(ctx: click.Context, session_id: Optional[str]) -> None:
    """Stop display playback."""
    session = _session_with_device(ctx, session_id)
    try:
        session.device.display.stop()
    except EdgeLensError as e:
        error(str(e))
    emit({"action": "stop"}, json_mode=ctx.obj["json_mode"], human="✓ display stopped")


@display_group.command("status")
@click.option("--session", "session_id", default=None)
@click.pass_context
def display_status(ctx: click.Context, session_id: Optional[str]) -> None:
    """Print the current display state."""
    session = _session_with_device(ctx, session_id)
    try:
        state = session.device.display.status()
    except EdgeLensError as e:
        error(str(e))
    emit(
        state,
        json_mode=ctx.obj["json_mode"],
        human=(
            f"ready:  {state.get('ready')}\n"
            f"state:  {state.get('state')}\n"
            f"source: {state.get('source') or '(none)'}"
        ),
    )
