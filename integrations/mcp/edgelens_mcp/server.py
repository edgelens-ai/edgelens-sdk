"""EdgeLens MCP server.

Exposes the Python SDK as a set of LLM tools over the Model Context Protocol.
Connect from Claude Desktop, Claude Code, Cursor, or any other MCP host.

Transport: stdio (default — host process spawns this server). HTTP streamable
is planned for the hosted variant.

Auth: `EDGELENS_API_KEY` in the env block of the MCP host config.

Tools mirror the SDK / CLI surface — see the README for the full list.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Literal, Optional

from edgelens.errors import EdgeLensError
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from edgelens_mcp.state import STATE

logger = logging.getLogger(__name__)

mcp = FastMCP("edgelens")


# The MCP server exposes operations that mutate the host filesystem
# (uploads) and the customer device (arbitrary shell exec). These are
# guarded by opt-in env flags so an LLM that lands here by mistake
# cannot brick a device or read arbitrary files.
_EXEC_ENABLED = os.environ.get("EDGELENS_MCP_EXEC_ENABLED") == "1"
_UPLOAD_ROOT_RAW = os.environ.get("EDGELENS_MCP_ALLOWED_UPLOAD_ROOT")
_UPLOAD_ROOT: Optional[Path] = (
    Path(_UPLOAD_ROOT_RAW).resolve() if _UPLOAD_ROOT_RAW else None
)

# A small denylist so even with exec
# opted in, the most obviously dangerous commands fail closed. Defence
# in depth — operators should pair this with their own MCP-host policy.
#
# No surrounding \b anchors: several patterns end in a non-word char
# (`rm -rf /`, the fork bomb's `{`), and a trailing \b requires a word
# char on the boundary — so `\b(...)\b` silently failed to match exactly
# those two headline cases. The alternatives are specific enough to
# search unanchored.
_EXEC_DENY = re.compile(
    r"("
    r"rm\s+-rf?\s+/|"
    r":\(\)\s*\{|"  # fork bomb
    r"mkfs|dd\s+if=|"
    r"shutdown|reboot|halt|poweroff|"
    r"chmod\s+-R\s+777\s+/|"
    r"curl\s+[^|]*\|\s*(sh|bash)|"
    r"wget\s+[^|]*\|\s*(sh|bash)"
    r")"
)


def _check_exec_enabled() -> None:
    """Refuse exec_command unless the operator opted in.

    Exec is arbitrary shell on the
    customer's camera. Default-deny — operator sets
    EDGELENS_MCP_EXEC_ENABLED=1 in the host config when they accept the
    risk for that session.
    """
    if not _EXEC_ENABLED:
        raise RuntimeError(
            "exec_command is disabled. The operator must set "
            "EDGELENS_MCP_EXEC_ENABLED=1 in the MCP host env to opt in. "
            "Arbitrary shell exec is gated "
            "behind an explicit opt-in flag."
        )


def _check_command_allowed(command: str) -> None:
    if _EXEC_DENY.search(command):
        raise RuntimeError(
            "Command rejected by the MCP exec denylist. "
            "Run it directly via SSH if you mean "
            "to."
        )


def _check_upload_path(local_path: str, *, label: str) -> Path:
    """Validate a local upload source against the allowed root.

    The MCP server can upload arbitrary files from the host fs to the customer device. The
    operator MUST set EDGELENS_MCP_ALLOWED_UPLOAD_ROOT to a directory
    they trust the LLM to read from. With no root set, every upload is
    refused — fail closed.
    """
    if _UPLOAD_ROOT is None:
        raise RuntimeError(
            f"{label} is disabled. The operator must set "
            "EDGELENS_MCP_ALLOWED_UPLOAD_ROOT=<dir> in the MCP host env "
            "to scope what the LLM can upload from. Uploads are "
            "default-deny so a prompt-injected LLM can't read "
            "~/.ssh, ~/.aws, etc."
        )
    try:
        resolved = Path(local_path).resolve(strict=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"{label}: path does not exist: {local_path}") from e
    try:
        resolved.relative_to(_UPLOAD_ROOT)
    except ValueError as e:
        raise RuntimeError(
            f"{label}: {local_path!r} resolves to {resolved}, which is "
            f"outside EDGELENS_MCP_ALLOWED_UPLOAD_ROOT={_UPLOAD_ROOT}. "
            "Rejecting to prevent path traversal / symlink escape."
        ) from e
    return resolved


# ToolAnnotations let MCP hosts present
# accurate UX (destructive / mutating / read-only) so the human in the
# loop sees the risk. We tag every tool below.
_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_MUTATES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
_LIFECYCLE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)


# ---- session lifecycle ------------------------------------------------------


@mcp.tool(annotations=_LIFECYCLE)
def create_session(
    device_type: str = "recamera-2002",
    os: Literal["stock-os", "recamagined"] = "stock-os",
    timeout_s: int = 3600,
    wait_ready: bool = True,
    wait_ready_timeout_s: int = 300,
) -> dict:
    """Allocate a remote EdgeLens camera for one test session.

    Call this when the user asks for a camera to test on, wants to run
    inference on real hardware, or asks about device availability. Returns
    the session id and (when wait_ready=True) the SSH details once the
    device has booted. Subsequent tools default to this session unless
    `session_id` is passed explicitly.

    Args:
        device_type: Hardware to allocate. Default "recamera-2002".
        os: OS to flash. "stock-os" (default) or "recamagined".
        timeout_s: Max session duration before auto-release.
        wait_ready: Block until status=ready before returning.
        wait_ready_timeout_s: Max wait for status=ready (only with wait_ready=True).
    """
    client = STATE.client()
    try:
        session = client.create_session(
            device_type=device_type, os=os, timeout=timeout_s
        )
        if wait_ready:
            session.wait_ready(timeout=wait_ready_timeout_s)
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(f"create_session failed: {e}") from e

    STATE.remember(session)
    return _session_to_dict(session)


@mcp.tool(annotations=_READ_ONLY)
def get_session(session_id: Optional[str] = None) -> dict:
    """Fetch the current state of a session.

    Defaults to the current session if no id is given.
    """
    try:
        session = STATE.get(session_id)
        session.refresh()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return _session_to_dict(session)


@mcp.tool(annotations=_READ_ONLY)
def wait_session_ready(
    session_id: Optional[str] = None, timeout_s: int = 300
) -> dict:
    """Block until a session reaches status=ready, then return its details."""
    try:
        session = STATE.get(session_id)
        session.wait_ready(timeout=timeout_s)
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return _session_to_dict(session)


@mcp.tool(annotations=_LIFECYCLE)
def release_session(session_id: Optional[str] = None) -> dict:
    """End a session and return the camera to the pool.

    Call this when the user is done testing or asks to clean up. Defaults to
    the current session. Idempotent — calling on an already-released session
    is a no-op.
    """
    try:
        session = STATE.get(session_id)
        session.release()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    sid = session.id
    STATE.forget(sid)
    return {"id": sid, "status": "released"}


@mcp.tool(annotations=_READ_ONLY)
def list_sessions() -> dict:
    """List sessions this MCP server has touched in the current process.

    The platform API doesn't yet expose a list endpoint, so this is a
    process-local echo. Use it to recover the id of a session you created
    earlier in the same conversation.
    """
    return {
        "current_session_id": STATE.current_session_id,
        "known_session_ids": STATE.list_session_ids(),
    }


# ---- device operations ------------------------------------------------------


@mcp.tool(annotations=_MUTATES)
def exec_command(
    command: str, session_id: Optional[str] = None, timeout_s: float = 60.0
) -> dict:
    """Run a shell command on the camera via SSH (proxied by the platform).

    Use this when the user asks to inspect, configure, or run arbitrary code
    on the device. Returns stdout, stderr, and exit_code. Non-zero exit codes
    are surfaced — they don't raise.

    Default-deny. Operator must set
    EDGELENS_MCP_EXEC_ENABLED=1 in the MCP host env to opt in. A small
    denylist refuses obviously destructive commands (rm -rf /, mkfs, fork
    bombs, piped curl/wget to sh) even when opted in.
    """
    _check_exec_enabled()
    _check_command_allowed(command)
    try:
        session = _require_ready(session_id)
        result = session.device.exec(command, timeout=timeout_s)
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }


@mcp.tool(annotations=_MUTATES)
def deploy_model(
    model_path: str,
    config_path: Optional[str] = None,
    extra_files: Optional[list[str]] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Deploy a model file to the camera.

    Call this when the user wants to test a model on the device. Accepts a
    local filesystem path the LLM hands over. Returns the platform's deploy
    response. On reCamaginedOS, files land in /userdata/Models/ readable but
    not executable; chmod +x a deployed binary before running it.

    Paths are
    validated against EDGELENS_MCP_ALLOWED_UPLOAD_ROOT — operator must set
    that env var or every deploy fails closed. Symlink escapes are caught
    by Path.resolve(strict=True).
    """
    _check_upload_path(model_path, label="deploy_model.model_path")
    if config_path is not None:
        _check_upload_path(config_path, label="deploy_model.config_path")
    if extra_files:
        for p in extra_files:
            _check_upload_path(p, label="deploy_model.extra_files")
    try:
        session = _require_ready(session_id)
        return dict(
            session.device.deploy(
                model=model_path, config=config_path, files=extra_files
            )
        )
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool(annotations=_READ_ONLY)
def get_ssh_details(session_id: Optional[str] = None) -> dict:
    """Return SSH connection details for the camera.

    Password is REDACTED by default to
    keep it out of the LLM transcript (Claude Desktop conversation
    files, MCP host logs, training-data sinks). Operator may opt in by
    setting EDGELENS_MCP_REVEAL_SECRETS=1 — only do this on a host
    that doesn't log MCP traffic.

    Alternative side-channel (also enabled by EDGELENS_MCP_REVEAL_SECRETS):
    the credential is written to a file path returned in
    ``password_file`` with 0o600 perms. The LLM hands the path to the
    user; the secret never sits in the transcript.
    """
    import os as _os
    import secrets as _secrets
    import tempfile as _tempfile

    try:
        session = _require_ready(session_id)
        creds = session.device.ssh()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e

    reveal = _os.environ.get("EDGELENS_MCP_REVEAL_SECRETS") == "1"
    body = {
        "user": creds.user,
        "host": creds.host,
        "port": creds.port,
        "ssh_command": f"ssh -p {creds.port} {creds.user}@{creds.host}",
    }
    if reveal:
        # Side-channel: write the password to a 0o600 file in the
        # operator's tempdir. LLM tells the user the path; the
        # cleartext never lands in the MCP transcript even when
        # reveal is on.
        suffix = "_" + _secrets.token_hex(8) + ".txt"
        path = _os.path.join(_tempfile.gettempdir(), "edgelens_ssh_pw" + suffix)
        fd = _os.open(path, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
        with _os.fdopen(fd, "w") as f:
            f.write(creds.password)
        body["password_file"] = path
        body["password"] = (
            "<written to password_file; not included in this response "
            "to keep it out of the MCP transcript>"
        )
    else:
        body["password"] = (
            "<redacted; set EDGELENS_MCP_REVEAL_SECRETS=1 to expose>"
        )
    return body


@mcp.tool(annotations=_READ_ONLY)
def get_device_info(session_id: Optional[str] = None) -> dict:
    """Return the device info report (hostname, hardware, firmware, NPU, ...)."""
    try:
        session = _require_ready(session_id)
        info = session.device.info()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return info.model_dump() if hasattr(info, "model_dump") else dict(info)


# ---- display control --------------------------------------------------------


@mcp.tool(annotations=_MUTATES)
def display_play(
    source: str, loop: bool = False, session_id: Optional[str] = None
) -> dict:
    """Play a video on the camera's external display."""
    try:
        session = _require_ready(session_id)
        session.device.display.play(source, loop=loop)
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {"action": "play", "source": source, "loop": loop}


@mcp.tool(annotations=_MUTATES)
def display_show(source: str, session_id: Optional[str] = None) -> dict:
    """Show a still image on the camera's external display."""
    try:
        session = _require_ready(session_id)
        session.device.display.show(source)
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {"action": "show", "source": source}


@mcp.tool(annotations=_MUTATES)
def display_stop(session_id: Optional[str] = None) -> dict:
    """Stop the camera's display playback."""
    try:
        session = _require_ready(session_id)
        session.device.display.stop()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {"action": "stop"}


@mcp.tool(annotations=_READ_ONLY)
def display_status(session_id: Optional[str] = None) -> dict:
    """Return the camera display's current state (ready/state/source)."""
    try:
        session = _require_ready(session_id)
        return dict(session.device.display.status())
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e


# ---- inference --------------------------------------------------------------


@mcp.tool(annotations=_MUTATES)
def inference_start(session_id: Optional[str] = None) -> dict:
    """Start on-device inference (stock OS only).

    Use this after `deploy_model` to begin scoring frames. Returns when the
    inference process has started — call `inference_stats` or
    `inference_run` to get results.
    """
    try:
        session = _require_ready(session_id)
        session.device.inference.start()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {"action": "start"}


@mcp.tool(annotations=_MUTATES)
def inference_stop(session_id: Optional[str] = None) -> dict:
    """Stop on-device inference."""
    try:
        session = _require_ready(session_id)
        session.device.inference.stop()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return {"action": "stop"}


@mcp.tool(annotations=_MUTATES)
def inference_once(session_id: Optional[str] = None) -> dict:
    """Run inference on a single frame and return the detections.

    Use this when the user wants a one-shot result, not a sustained metric.
    """
    try:
        session = _require_ready(session_id)
        return dict(session.device.inference.once())
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e


@mcp.tool(annotations=_READ_ONLY)
def inference_stats(session_id: Optional[str] = None) -> dict:
    """Return a point-in-time inference snapshot (fps, latency_ms, ...).

    Use this for a quick health check during a running inference. For
    aggregated statistics over a window, call `inference_run`.
    """
    try:
        session = _require_ready(session_id)
        snap = session.device.inference.snapshot()
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)


@mcp.tool(annotations=_MUTATES)
def inference_run(
    duration_s: float = 30.0,
    collect_frames: bool = False,
    session_id: Optional[str] = None,
) -> dict:
    """Run inference for a duration and return aggregated stats.

    Use this when the user wants to benchmark or validate a model. Returns
    duration_s, total_frames, fps percentiles, latency percentiles, and
    optionally per-frame detections.
    """
    try:
        session = _require_ready(session_id)
        stats = session.device.inference.run(
            duration=duration_s, collect_frames=collect_frames
        )
    except (EdgeLensError, ValueError) as e:
        raise RuntimeError(str(e)) from e
    return stats.model_dump() if hasattr(stats, "model_dump") else dict(stats)


# ---- helpers ----------------------------------------------------------------


def _require_ready(session_id: Optional[str]):  # type: ignore[no-untyped-def]
    """Resolve the session and refuse if it isn't ready yet."""
    session = STATE.get(session_id)
    if session.status.value != "ready":
        raise ValueError(
            f"session {session.id} is in state {session.status.value}, not "
            "ready. Call `wait_session_ready` first."
        )
    return session


def _session_to_dict(session) -> dict:  # type: ignore[no-untyped-def]
    payload: dict = {"id": session.id, "status": session.status.value}
    conn = getattr(session, "_connection", None)
    if conn is not None:
        payload["device"] = {
            "mac": conn.mac,
            "host": conn.host,
            "ssh_port": conn.ssh_port,
            "ssh_user": conn.ssh_user,
            "os": conn.os.value,
        }
    if session.expires_at:
        payload["expires_at"] = session.expires_at
    return payload


def run() -> None:
    """Entry point. Configured via the `edgelens-mcp` console script.

    Log the security posture so the
    operator can see in their host logs which dangerous tools are gated
    vs opted-in for this process.
    """
    logger.warning(
        "edgelens-mcp starting | exec_command=%s | upload_allowed_root=%s",
        "ENABLED" if _EXEC_ENABLED else "disabled (default)",
        str(_UPLOAD_ROOT) if _UPLOAD_ROOT else "disabled (default)",
    )
    mcp.run()


if __name__ == "__main__":
    run()
