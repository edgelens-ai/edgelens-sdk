"""``edgelens session`` subcommands."""

from __future__ import annotations

from typing import Optional

import click
from edgelens.errors import EdgeLensError

from edgelens_cli.client import build_client
from edgelens_cli.commands._resolve import resolve_session_id
from edgelens_cli.output import emit, error
from edgelens_cli.state import clear_current_session, load_state, set_current_session


@click.group(name="session")
def session_group() -> None:
    """Create, inspect, and release device sessions."""


@session_group.command("create")
@click.option(
    "--device", "device_type", default="recamera-2002",
    help="Device type to allocate (default: recamera-2002).",
)
@click.option(
    "--os", "os_type", default="stock-os",
    help="Which OS to flash (default: stock-os; alt: recamagined).",
)
@click.option(
    "--timeout", "timeout_s", default=3600, type=int,
    help="Max session duration in seconds (default: 3600).",
)
@click.option(
    "--wait/--no-wait", default=True,
    help="Block until status=ready (default: wait).",
)
@click.option(
    "--wait-timeout", default=300, type=int,
    help="Seconds to wait for ready (only with --wait, default: 300).",
)
@click.pass_context
def session_create(
    ctx: click.Context,
    device_type: str,
    os_type: str,
    timeout_s: int,
    wait: bool,
    wait_timeout: int,
) -> None:
    """Allocate a new device. Sets it as the current session on success."""
    client = build_client(ctx.obj.get("api_key"), ctx.obj.get("base_url"))
    try:
        session = client.create_session(
            device_type=device_type, os=os_type, timeout=timeout_s,
        )
    except EdgeLensError as e:
        error(str(e))
    set_current_session(session.id)
    if wait:
        try:
            session.wait_ready(timeout=wait_timeout)
        except EdgeLensError as e:
            emit(
                {"id": session.id, "status": session.status.value, "error": str(e)},
                json_mode=ctx.obj["json_mode"],
                human=f"✗ {session.id}: {e}",
            )
            ctx.exit(1)

    emit(
        _session_payload(session),
        json_mode=ctx.obj["json_mode"],
        human=_human_session(session),
    )


@session_group.command("get")
@click.argument("session_id", required=False)
@click.pass_context
def session_get(ctx: click.Context, session_id: Optional[str]) -> None:
    """Show one session. Defaults to the current session."""
    session_id = resolve_session_id(session_id)
    client = build_client(ctx.obj.get("api_key"), ctx.obj.get("base_url"))
    try:
        session = client.get_session(session_id)
    except EdgeLensError as e:
        error(str(e))
    emit(
        _session_payload(session),
        json_mode=ctx.obj["json_mode"],
        human=_human_session(session),
    )


@session_group.command("wait")
@click.argument("session_id", required=False)
@click.option("--timeout", "wait_timeout", default=300, type=int)
@click.pass_context
def session_wait(ctx: click.Context, session_id: Optional[str], wait_timeout: int) -> None:
    """Block until a session reaches status=ready."""
    session_id = resolve_session_id(session_id)
    client = build_client(ctx.obj.get("api_key"), ctx.obj.get("base_url"))
    session = client.get_session(session_id)
    try:
        session.wait_ready(timeout=wait_timeout)
    except EdgeLensError as e:
        error(str(e))
    emit(
        _session_payload(session),
        json_mode=ctx.obj["json_mode"],
        human=_human_session(session),
    )


@session_group.command("release")
@click.argument("session_id", required=False)
@click.pass_context
def session_release(ctx: click.Context, session_id: Optional[str]) -> None:
    """End a session. Defaults to the current session and clears its pointer."""
    session_id = resolve_session_id(session_id)
    client = build_client(ctx.obj.get("api_key"), ctx.obj.get("base_url"))
    try:
        session = client.get_session(session_id)
        session.release()
    except EdgeLensError as e:
        error(str(e))

    # Clear `current` only if we just released what was pointed at.
    state = load_state()
    if state.current_session_id == session_id:
        clear_current_session()

    emit(
        {"id": session_id, "status": "released"},
        json_mode=ctx.obj["json_mode"],
        human=f"✓ released {session_id}",
    )


@session_group.command("list")
@click.pass_context
def session_list(ctx: click.Context) -> None:
    """Show recently-touched sessions from local state.

    The platform API doesn't yet expose a per-key list endpoint, so
    this is a local-state echo of the last sessions this CLI touched.
    """
    state = load_state()
    payload = {
        "current_session_id": state.current_session_id,
        "recent": state.recent,
    }
    human_lines = []
    if state.current_session_id:
        human_lines.append(f"* {state.current_session_id} (current)")
    for sid in state.recent:
        if sid != state.current_session_id:
            human_lines.append(f"  {sid}")
    human = "\n".join(human_lines) if human_lines else "(no recent sessions)"
    emit(payload, json_mode=ctx.obj["json_mode"], human=human)


def _session_payload(session) -> dict:  # type: ignore[no-untyped-def]
    payload: dict = {"id": session.id, "status": session.status.value}
    conn = getattr(session, "_connection", None)
    if conn is not None:
        payload["device"] = {
            "mac": conn.mac, "host": conn.host, "ssh_port": conn.ssh_port,
            "ssh_user": conn.ssh_user, "os": conn.os.value,
        }
    if session.expires_at:
        payload["expires_at"] = session.expires_at
    return payload


def _human_session(session) -> str:  # type: ignore[no-untyped-def]
    lines = [f"id:     {session.id}", f"status: {session.status.value}"]
    conn = getattr(session, "_connection", None)
    if conn is not None:
        lines.extend([
            f"device: {conn.os.value} ({conn.mac})",
            f"ssh:    {conn.ssh_user}@{conn.host}:{conn.ssh_port}",
        ])
    if session.expires_at:
        lines.append(f"expires: {session.expires_at}")
    return "\n".join(lines)
