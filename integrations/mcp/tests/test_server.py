"""Unit tests for the MCP server tool functions.

We test the tool functions directly, bypassing the MCP transport.
FastMCP's `@mcp.tool()` returns the wrapped function unchanged, so we
call it with normal Python kwargs. (The registered Tool object — with
annotations, schema, etc. — lives in `server.mcp._tool_manager`.)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from edgelens import EdgeLensClient
from edgelens.errors import EdgeLensError
from edgelens.types import OSType
from edgelens_mcp import server, state


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> state.ServerState:
    """Reset the module-level STATE singleton between tests."""
    fresh = state.ServerState()
    monkeypatch.setattr(state, "STATE", fresh)
    monkeypatch.setattr(server, "STATE", fresh)
    return fresh


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch, _fresh_state: state.ServerState) -> MagicMock:
    """Replace `STATE.client()` with a MagicMock so no SDK construction happens."""
    client = MagicMock()
    monkeypatch.setattr(_fresh_state, "client", lambda: client)
    return client


def _ready_session(session_id: str = "sess_x", os: str = "stock-os"):
    session = MagicMock()
    session.id = session_id
    session.status.value = "ready"
    session.expires_at = None
    session._connection.mac = "aa:bb:cc:00:00:01"
    session._connection.host = "192.0.2.42"
    session._connection.ssh_port = 30007
    session._connection.ssh_user = "recamera"
    session._connection.os.value = os
    return session


# ---- session lifecycle ------------------------------------------------------


def test_create_session_returns_session_dict_and_remembers(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    fake_client.create_session.return_value = fake_session

    result = server.create_session(
        device_type="recamera-2002", os="stock-os", timeout_s=600, wait_ready=True,
    )
    assert result["id"] == "sess_x"
    assert result["status"] == "ready"
    assert result["device"]["host"] == "192.0.2.42"
    fake_client.create_session.assert_called_once_with(
        device_type="recamera-2002", os="stock-os", timeout=600,
    )
    fake_session.wait_ready.assert_called_once_with(timeout=300)
    assert _fresh_state.current_session_id == "sess_x"


def test_create_session_no_wait_skips_wait_ready(fake_client: MagicMock):
    fake_session = _ready_session()
    fake_session.status.value = "flashing"
    fake_client.create_session.return_value = fake_session

    server.create_session(wait_ready=False)
    fake_session.wait_ready.assert_not_called()


def test_create_session_default_os_is_a_valid_os_type(fake_client: MagicMock):
    fake_client.create_session.return_value = _ready_session()

    server.create_session(wait_ready=False)
    OSType(fake_client.create_session.call_args.kwargs["os"])


def test_create_session_invalid_os_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch, _fresh_state: state.ServerState
):
    client = EdgeLensClient(api_key="el_test_k")
    monkeypatch.setattr(_fresh_state, "client", lambda: client)

    with pytest.raises(RuntimeError, match="create_session failed"):
        server.create_session(os="stock", wait_ready=False)


def test_create_session_releases_when_wait_ready_fails(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    original = TimeoutError("never became ready")
    fake_session.wait_ready.side_effect = original
    fake_client.create_session.return_value = fake_session

    with pytest.raises(TimeoutError) as excinfo:
        server.create_session()
    assert excinfo.value is original
    fake_session.release.assert_called_once_with()
    assert _fresh_state.current_session_id is None


def test_create_session_releases_on_sdk_error_and_keeps_it_as_cause(
    fake_client: MagicMock,
):
    fake_session = _ready_session()
    original = EdgeLensError("session errored")
    fake_session.wait_ready.side_effect = original
    fake_client.create_session.return_value = fake_session

    with pytest.raises(RuntimeError, match="create_session failed") as excinfo:
        server.create_session()
    assert excinfo.value.__cause__ is original
    fake_session.release.assert_called_once_with()


def test_create_session_releases_on_keyboard_interrupt(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    fake_session.wait_ready.side_effect = KeyboardInterrupt
    fake_client.create_session.return_value = fake_session

    with pytest.raises(KeyboardInterrupt):
        server.create_session()
    fake_session.release.assert_called_once_with()
    assert _fresh_state.list_session_ids() == []


def test_create_session_release_failure_does_not_mask_original(
    fake_client: MagicMock, caplog: pytest.LogCaptureFixture
):
    fake_session = _ready_session()
    original = TimeoutError("never became ready")
    fake_session.wait_ready.side_effect = original
    fake_session.release.side_effect = EdgeLensError("release failed")
    fake_client.create_session.return_value = fake_session

    with caplog.at_level("WARNING", logger=server.logger.name):
        with pytest.raises(TimeoutError) as excinfo:
            server.create_session()
    assert excinfo.value is original
    fake_session.release.assert_called_once_with()
    assert "release failed" in caplog.text


def test_create_session_tool_schema_lists_canonical_os_values():
    tool = server.mcp._tool_manager.get_tool("create_session")
    os_schema = tool.parameters["properties"]["os"]
    assert os_schema["enum"] == ["stock-os", "recamagined"]
    assert os_schema["default"] == "stock-os"


def test_get_session_defaults_to_current(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session("sess_cur")
    _fresh_state.remember(fake_session)

    result = server.get_session()
    assert result["id"] == "sess_cur"
    fake_session.refresh.assert_called_once()


def test_get_session_unknown_session_refused_by_default(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    with pytest.raises(
        RuntimeError, match="EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS=1"
    ):
        server.get_session(session_id="sess_other")
    fake_client.get_session.assert_not_called()
    assert _fresh_state.list_session_ids() == []


@pytest.mark.parametrize(
    "call",
    [
        lambda sid: server.release_session(session_id=sid),
        lambda sid: server.wait_session_ready(session_id=sid),
        lambda sid: server.get_device_info(session_id=sid),
        lambda sid: server.inference_stop(session_id=sid),
    ],
    ids=["release", "wait_ready", "device_info", "inference_stop"],
)
def test_tools_unknown_session_refused(
    fake_client: MagicMock, _fresh_state: state.ServerState, call
):
    with pytest.raises(RuntimeError, match="not created by this MCP server"):
        call("sess_other")
    fake_client.get_session.assert_not_called()


def test_exec_command_unknown_session_refused(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(server, "_EXEC_ENABLED", True)
    _fresh_state.remember(_ready_session("sess_mine"))

    with pytest.raises(RuntimeError, match="EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS"):
        server.exec_command(command="id", session_id="sess_other")
    fake_client.get_session.assert_not_called()


@pytest.mark.parametrize("value", ["0", "true", ""])
def test_get_session_unknown_session_refused_without_exact_opt_in(
    fake_client: MagicMock, monkeypatch: pytest.MonkeyPatch, value: str
):
    monkeypatch.setenv("EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS", value)
    with pytest.raises(RuntimeError, match="not created by this MCP server"):
        server.get_session(session_id="sess_other")
    fake_client.get_session.assert_not_called()


def test_get_session_unknown_session_allowed_with_opt_in(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS", "1")
    fake_session = _ready_session("sess_new")
    fake_client.get_session.return_value = fake_session

    result = server.get_session(session_id="sess_new")
    assert result["id"] == "sess_new"
    fake_client.get_session.assert_called_once_with("sess_new")


def test_release_session_unknown_session_allowed_with_opt_in(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS", "1")
    fake_session = _ready_session("sess_ext")
    fake_client.get_session.return_value = fake_session

    result = server.release_session(session_id="sess_ext")
    assert result == {"id": "sess_ext", "status": "released"}
    fake_session.release.assert_called_once()
    assert "sess_ext" not in _fresh_state.list_session_ids()


def test_created_session_resolves_without_opt_in(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session("sess_created")
    fake_client.create_session.return_value = fake_session
    server.create_session(wait_ready=False)

    result = server.get_session(session_id="sess_created")
    assert result["id"] == "sess_created"
    fake_client.get_session.assert_not_called()


def test_get_session_no_current_raises(fake_client: MagicMock):
    with pytest.raises(RuntimeError, match="No session id"):
        server.get_session()


def test_release_session_calls_release_and_clears(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session("sess_drop")
    _fresh_state.remember(fake_session)

    result = server.release_session()
    assert result == {"id": "sess_drop", "status": "released"}
    fake_session.release.assert_called_once()
    assert _fresh_state.current_session_id is None


def test_list_sessions_echoes_local_state(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    _fresh_state.remember(_ready_session("sess_a"))
    _fresh_state.remember(_ready_session("sess_b"))

    result = server.list_sessions()
    assert result["current_session_id"] == "sess_b"
    assert set(result["known_session_ids"]) == {"sess_a", "sess_b"}


# ---- device operations ------------------------------------------------------


def test_exec_command_propagates_exit_code(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(server, "_EXEC_ENABLED", True)  # opt in
    fake_session = _ready_session()
    fake_session.device.exec.return_value = MagicMock(
        stdout="hi\n", stderr="", exit_code=0,
    )
    _fresh_state.remember(fake_session)

    result = server.exec_command(command="echo hi", timeout_s=5.0)
    assert result == {"stdout": "hi\n", "stderr": "", "exit_code": 0}
    fake_session.device.exec.assert_called_once_with("echo hi", timeout=5.0)


def test_exec_command_requires_ready_session(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(server, "_EXEC_ENABLED", True)  # past the opt-in gate
    fake_session = _ready_session()
    fake_session.status.value = "flashing"
    _fresh_state.remember(fake_session)

    with pytest.raises(RuntimeError, match="not.*ready"):
        server.exec_command(command="ls")


def test_deploy_model_passes_through(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch, tmp_path,
):
    # deploy_model validates paths against the upload root —
    # point it at a temp dir with real files.
    monkeypatch.setattr(server, "_UPLOAD_ROOT", tmp_path)
    model = tmp_path / "m.cvimodel"
    model.write_bytes(b"m")
    config = tmp_path / "c.json"
    config.write_text("{}")
    extra = tmp_path / "extra"
    extra.write_bytes(b"x")

    fake_session = _ready_session()
    fake_session.device.deploy.return_value = {"success": True}
    _fresh_state.remember(fake_session)

    result = server.deploy_model(
        model_path=str(model), config_path=str(config), extra_files=[str(extra)],
    )
    assert result == {"success": True}
    fake_session.device.deploy.assert_called_once_with(
        model=str(model), config=str(config), files=[str(extra)],
    )


def test_get_ssh_details_includes_ssh_command(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    fake_session.device.ssh.return_value = MagicMock(
        user="recamera", host="192.0.2.42", port=30007, password="pw",
    )
    _fresh_state.remember(fake_session)

    result = server.get_ssh_details()
    assert result["ssh_command"] == "ssh -p 30007 recamera@192.0.2.42"


def test_get_ssh_details_redacts_password_by_default(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    """Password masked by default to
    keep it out of the LLM transcript."""
    monkeypatch.delenv("EDGELENS_MCP_REVEAL_SECRETS", raising=False)
    fake_session = _ready_session()
    fake_session.device.ssh.return_value = MagicMock(
        user="recamera", host="192.0.2.42", port=30007, password="hunter2",
    )
    _fresh_state.remember(fake_session)

    result = server.get_ssh_details()
    assert "hunter2" not in str(result)
    assert "redacted" in result["password"]
    assert "password_file" not in result


def test_get_ssh_details_reveal_writes_password_file(
    fake_client: MagicMock, _fresh_state: state.ServerState,
    monkeypatch: pytest.MonkeyPatch,
):
    """When the operator opts in, the password goes to a 0o600 file —
    the cleartext still doesn't sit in the LLM transcript."""
    import os, stat
    monkeypatch.setenv("EDGELENS_MCP_REVEAL_SECRETS", "1")
    fake_session = _ready_session()
    fake_session.device.ssh.return_value = MagicMock(
        user="recamera", host="192.0.2.42", port=30007, password="hunter2",
    )
    _fresh_state.remember(fake_session)

    result = server.get_ssh_details()
    path = result["password_file"]
    try:
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "hunter2"
        # File mode 0o600 — only the owner can read.
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600
        # The MCP response body itself does NOT contain the cleartext.
        assert "hunter2" not in result["password"]
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---- display ----------------------------------------------------------------


def test_display_play_passes_args(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    _fresh_state.remember(fake_session)

    server.display_play(source="https://x.com/v.mp4", loop=True)
    fake_session.device.display.play.assert_called_once_with(
        "https://x.com/v.mp4", loop=True,
    )


# ---- inference --------------------------------------------------------------


def test_inference_run_returns_stats_dict(
    fake_client: MagicMock, _fresh_state: state.ServerState
):
    fake_session = _ready_session()
    stats = MagicMock()
    stats.model_dump.return_value = {
        "duration_s": 30, "total_frames": 450,
        "fps": {"avg": 15.2, "p95": 14.9},
        "latency_ms": {"p95": 70.0},
    }
    fake_session.device.inference.run.return_value = stats
    _fresh_state.remember(fake_session)

    result = server.inference_run(duration_s=30.0, collect_frames=False)
    assert result["fps"]["avg"] == 15.2
    fake_session.device.inference.run.assert_called_once_with(
        duration=30.0, collect_frames=False,
    )


# ---- state ------------------------------------------------------------------


def test_state_client_raises_without_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EDGELENS_API_KEY", raising=False)
    s = state.ServerState()
    with pytest.raises(RuntimeError, match="EDGELENS_API_KEY"):
        s.client()


def test_state_client_threads_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDGELENS_API_KEY", "el_test_k")
    monkeypatch.setenv("EDGELENS_BASE_URL", "https://custom.test")
    s = state.ServerState()
    with patch("edgelens_mcp.state.EdgeLensClient") as ctor:
        s.client()
    ctor.assert_called_once_with(api_key="el_test_k", base_url="https://custom.test")
