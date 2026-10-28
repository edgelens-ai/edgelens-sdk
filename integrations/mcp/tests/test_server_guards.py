"""MCP server guards: exec opt-in, upload path jail, tool annotations.

Covers:
  exec_command opt-in, and that no command filter pretends to make it safe.
  deploy_model honors EDGELENS_MCP_ALLOWED_UPLOAD_ROOT
    (CWE-862 default-deny + CWE-285 path containment).
  ToolAnnotations + boot-time guard log.

We re-import `server` after monkeypatching the env so the module-level
constants pick up the new values.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def reload_server(monkeypatch: pytest.MonkeyPatch):
    """Yield a function that re-imports edgelens_mcp.server after the
    test has set the relevant env vars. Restores the unconfigured
    defaults on teardown."""

    def _reload():
        from edgelens_mcp import server  # noqa: WPS433
        importlib.reload(server)
        return server

    yield _reload
    # Force a clean reload back to defaults so other tests aren't affected.
    monkeypatch.delenv("EDGELENS_MCP_EXEC_ENABLED", raising=False)
    monkeypatch.delenv("EDGELENS_MCP_ALLOWED_UPLOAD_ROOT", raising=False)
    from edgelens_mcp import server  # noqa: WPS433
    importlib.reload(server)


def _ready_session(session_id: str = "sess_x"):
    session = MagicMock()
    session.id = session_id
    session.status.value = "ready"
    session.device.exec.return_value = MagicMock(stdout="ok", stderr="", exit_code=0)
    session.device.deploy.return_value = {"deployed": True}
    return session


# ---- exec_command ------------------------------------------------------


def test_exec_command_default_deny(reload_server, monkeypatch):
    monkeypatch.delenv("EDGELENS_MCP_EXEC_ENABLED", raising=False)
    server = reload_server()
    with pytest.raises(RuntimeError, match="EDGELENS_MCP_EXEC_ENABLED"):
        server.exec_command(command="echo hi")


def test_exec_command_disabled_never_reaches_the_device(reload_server, monkeypatch):
    monkeypatch.delenv("EDGELENS_MCP_EXEC_ENABLED", raising=False)
    server = reload_server()
    session = _ready_session()
    monkeypatch.setattr(server, "_require_ready", lambda _sid: session)
    with pytest.raises(RuntimeError, match="EDGELENS_MCP_EXEC_ENABLED"):
        server.exec_command(command="uname -a")
    session.device.exec.assert_not_called()


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_exec_command_only_exact_opt_in_enables(reload_server, monkeypatch, value):
    monkeypatch.setenv("EDGELENS_MCP_EXEC_ENABLED", value)
    server = reload_server()
    with pytest.raises(RuntimeError, match="EDGELENS_MCP_EXEC_ENABLED"):
        server.exec_command(command="echo hi")


def test_exec_command_disabled_error_states_unrestricted_shell(reload_server, monkeypatch):
    monkeypatch.delenv("EDGELENS_MCP_EXEC_ENABLED", raising=False)
    server = reload_server()
    with pytest.raises(RuntimeError, match="unrestricted shell"):
        server.exec_command(command="echo hi")


def test_exec_command_has_no_command_filter(reload_server, monkeypatch):
    """Once opted in, commands go to the device verbatim.

    No pattern filter exists to give false assurance; the docs and tool
    description say exec is an unrestricted shell.
    """
    monkeypatch.setenv("EDGELENS_MCP_EXEC_ENABLED", "1")
    server = reload_server()
    session = _ready_session()
    monkeypatch.setattr(server, "_require_ready", lambda _sid: session)
    command = "rm -rf /"
    server.exec_command(command=command)
    session.device.exec.assert_called_once_with(command, timeout=60.0)


def test_exec_command_tool_description_states_unrestricted_shell(reload_server):
    server = reload_server()
    description = server.mcp._tool_manager.get_tool("exec_command").description
    assert "unrestricted shell" in description
    assert "EDGELENS_MCP_EXEC_ENABLED=1" in description
    assert "denylist" not in description


def test_exec_command_allowed_when_opted_in(reload_server, monkeypatch):
    monkeypatch.setenv("EDGELENS_MCP_EXEC_ENABLED", "1")
    server = reload_server()
    monkeypatch.setattr(server, "_require_ready", lambda _sid: _ready_session())
    out = server.exec_command(command="uname -a")
    assert out["exit_code"] == 0
    assert out["stdout"] == "ok"


# ---- deploy_model path-jail ------------------------


def test_deploy_model_default_deny(reload_server, monkeypatch, tmp_path):
    monkeypatch.delenv("EDGELENS_MCP_ALLOWED_UPLOAD_ROOT", raising=False)
    server = reload_server()
    target = tmp_path / "m.cvimodel"
    target.write_bytes(b"m")
    with pytest.raises(RuntimeError, match="EDGELENS_MCP_ALLOWED_UPLOAD_ROOT"):
        server.deploy_model(model_path=str(target))


def test_deploy_model_rejects_symlink_escape(reload_server, monkeypatch, tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"hunter2")
    link = root / "evil.cvimodel"
    link.symlink_to(secret)
    monkeypatch.setenv("EDGELENS_MCP_ALLOWED_UPLOAD_ROOT", str(root))
    server = reload_server()
    with pytest.raises(RuntimeError, match="outside"):
        server.deploy_model(model_path=str(link))


def test_deploy_model_validates_every_path(reload_server, monkeypatch, tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    model = root / "m.cvimodel"
    model.write_bytes(b"m")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"hunter2")
    monkeypatch.setenv("EDGELENS_MCP_ALLOWED_UPLOAD_ROOT", str(root))
    server = reload_server()
    monkeypatch.setattr(server, "_require_ready", lambda _sid: _ready_session())
    with pytest.raises(RuntimeError, match="outside"):
        server.deploy_model(
            model_path=str(model),
            extra_files=[str(outside)],
        )


# ---- ToolAnnotations ---------------------------------------------------


def test_tool_annotations_present(reload_server):
    server = reload_server()
    # Annotations live on the registered Tool objects in the FastMCP
    # tool manager — @mcp.tool() returns the plain function, so the
    # annotations are not attributes on server.<tool>.
    def ann(name):
        return server.mcp._tool_manager.get_tool(name).annotations

    assert ann("exec_command") is not None
    assert ann("exec_command").destructiveHint is True
    assert ann("get_session").readOnlyHint is True
    assert ann("deploy_model").destructiveHint is True
