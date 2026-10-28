"""Device operations on the current (or named) session."""

from __future__ import annotations

from typing import Optional

import click
from edgelens.errors import EdgeLensError

from edgelens_cli.client import build_client
from edgelens_cli.commands._resolve import resolve_session_id
from edgelens_cli.output import emit, error


def _session_with_device(ctx: click.Context, session_id: Optional[str]):  # type: ignore[no-untyped-def]
    """Resolve session id → ready Session, or click-error if not ready."""
    sid = resolve_session_id(session_id)
    client = build_client(ctx.obj.get("api_key"), ctx.obj.get("base_url"))
    try:
        session = client.get_session(sid)
    except EdgeLensError as e:
        error(str(e))
    if session.status.value != "ready":
        error(
            f"session {sid} is in state {session.status.value}, not ready. "
            "Run `edgelens session wait` first.",
            exit_code=2,
        )
    return session


@click.command("exec")
@click.argument("command_str")
@click.option("--session", "session_id", default=None, help="Session id (default: current).")
@click.option("--timeout", default=60.0, type=float, help="Command timeout in seconds.")
@click.pass_context
def exec_cmd(
    ctx: click.Context, command_str: str, session_id: Optional[str], timeout: float
) -> None:
    """Run a shell command on the camera and print stdout / exit code."""
    session = _session_with_device(ctx, session_id)
    try:
        result = session.device.exec(command_str, timeout=timeout)
    except EdgeLensError as e:
        error(str(e))

    payload = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }
    human_parts = []
    if result.stdout:
        human_parts.append(result.stdout.rstrip())
    if result.stderr:
        human_parts.append(click.style(result.stderr.rstrip(), fg="red"))
    if not human_parts:
        human_parts.append(f"(no output, exit={result.exit_code})")
    emit(payload, json_mode=ctx.obj["json_mode"], human="\n".join(human_parts))
    if result.exit_code != 0:
        ctx.exit(result.exit_code if 0 < result.exit_code < 128 else 1)


@click.command("deploy")
@click.argument("model_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--file", "extra_files", type=click.Path(exists=True, dir_okay=False),
    multiple=True, help="Additional supporting files (repeatable).",
)
@click.option("--session", "session_id", default=None)
@click.pass_context
def deploy_cmd(
    ctx: click.Context,
    model_path: str,
    config_path: Optional[str],
    extra_files: tuple,
    session_id: Optional[str],
) -> None:
    """Deploy a model file to the camera."""
    session = _session_with_device(ctx, session_id)
    try:
        result = session.device.deploy(
            model=model_path,
            config=config_path,
            files=list(extra_files) or None,
        )
    except EdgeLensError as e:
        error(str(e))
    emit(
        result,
        json_mode=ctx.obj["json_mode"],
        human=f"✓ deployed {model_path}",
    )


@click.command("info")
@click.option("--session", "session_id", default=None)
@click.pass_context
def info_cmd(ctx: click.Context, session_id: Optional[str]) -> None:
    """Print the device info report."""
    session = _session_with_device(ctx, session_id)
    try:
        info = session.device.info()
    except EdgeLensError as e:
        error(str(e))
    emit(
        info.model_dump() if hasattr(info, "model_dump") else info,
        json_mode=ctx.obj["json_mode"],
        human=(
            f"hostname: {info.hostname}\n"
            f"hardware: {info.hardware}\n"
            f"firmware: {info.firmware}"
        ),
    )


@click.command("ssh")
@click.option("--session", "session_id", default=None)
@click.option(
    "--show-password", is_flag=True, default=False,
    help="Print the SSH password in cleartext (or set EDGELENS_SHOW_PASSWORD=1).",
)
@click.pass_context
def ssh_cmd(
    ctx: click.Context, session_id: Optional[str], show_password: bool,
) -> None:
    """Print SSH connection details.

    Password is masked by default in
    both --json and human modes. The plaintext is only emitted when
    --show-password is passed or EDGELENS_SHOW_PASSWORD=1 in the env,
    so the credential never reaches stdout or CI logs by accident.
    """
    import os as _os
    reveal = show_password or _os.environ.get("EDGELENS_SHOW_PASSWORD") == "1"

    session = _session_with_device(ctx, session_id)
    try:
        creds = session.device.ssh()
    except EdgeLensError as e:
        error(str(e))

    payload = {
        "user": creds.user, "host": creds.host, "port": creds.port,
    }
    if reveal:
        payload["password"] = creds.password

    password_line = (
        f"password: {creds.password}\n"
        if reveal
        else "password: <hidden — pass --show-password to reveal>\n"
    )
    human = (
        f"user:     {creds.user}\n"
        f"host:     {creds.host}\n"
        f"port:     {creds.port}\n"
        f"{password_line}"
        "\n"
        f"ssh -p {creds.port} {creds.user}@{creds.host}"
    )
    emit(payload, json_mode=ctx.obj["json_mode"], human=human)
