"""CLI smoke tests via click's CliRunner.

We stub `EdgeLensClient` end-to-end so the tests stay hermetic and don't
need a running EdgeLens API. The state files are redirected to a tmp dir
per-test.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from edgelens_cli import state as state_mod
from edgelens_cli.main import cli


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ~/.edgelens at a per-test tmp dir."""
    monkeypatch.setattr(state_mod, "DEFAULT_DIR", tmp_path / "edgelens")
    monkeypatch.setattr(state_mod, "CONFIG_PATH", tmp_path / "edgelens" / "config.json")
    monkeypatch.setattr(state_mod, "STATE_PATH", tmp_path / "edgelens" / "state.json")
    # Strip env-var fallbacks so tests don't pick up the dev's real key.
    monkeypatch.delenv("EDGELENS_API_KEY", raising=False)
    monkeypatch.delenv("EDGELENS_BASE_URL", raising=False)


def _runner() -> CliRunner:
    return CliRunner()


# ---- login / logout / use --------------------------------------------------


def test_login_saves_config_and_logout_clears_it():
    r = _runner().invoke(cli, ["login", "--api-key", "el_test_xyz"])
    assert r.exit_code == 0, r.output
    assert state_mod.load_config().api_key == "el_test_xyz"

    r2 = _runner().invoke(cli, ["logout"])
    assert r2.exit_code == 0, r2.output
    assert state_mod.load_config().api_key is None


def test_login_json_mode_emits_json():
    r = _runner().invoke(cli, ["--json", "login", "--api-key", "k"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["saved"] is True


def test_login_prompts_with_hidden_input_on_a_tty(monkeypatch: pytest.MonkeyPatch):
    from edgelens_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_stdin_is_tty", lambda: True)
    r = _runner().invoke(cli, ["login"], input="el_test_prompted\n")
    assert r.exit_code == 0, r.output
    assert "API key" in r.output
    assert "el_test_prompted" not in r.output
    assert state_mod.load_config().api_key == "el_test_prompted"


def test_login_reads_key_from_stdin_when_not_a_tty(monkeypatch: pytest.MonkeyPatch):
    from edgelens_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_stdin_is_tty", lambda: False)
    r = _runner().invoke(cli, ["login"], input="el_test_piped\n")
    assert r.exit_code == 0, r.output
    assert "API key" not in r.output
    assert "el_test_piped" not in r.output
    assert state_mod.load_config().api_key == "el_test_piped"


def test_login_rejects_empty_stdin(monkeypatch: pytest.MonkeyPatch):
    from edgelens_cli import main as main_mod

    monkeypatch.setattr(main_mod, "_stdin_is_tty", lambda: False)
    r = _runner().invoke(cli, ["login"], input="\n")
    assert r.exit_code == 2
    assert state_mod.load_config().api_key is None


def test_use_sets_current_session():
    r = _runner().invoke(cli, ["use", "sess_abc"])
    assert r.exit_code == 0
    assert state_mod.load_state().current_session_id == "sess_abc"


def test_use_rejects_bad_id_shape():
    r = _runner().invoke(cli, ["use", "notvalid"])
    assert r.exit_code == 2
    assert "sess_" in r.output


# ---- session create / get / release ----------------------------------------


def _patch_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub EdgeLensClient construction everywhere it's used.

    `from edgelens_cli.client import build_client` in each command
    module re-binds the symbol into that module's namespace at import
    time, so a single monkeypatch on `edgelens_cli.client.build_client`
    misses every consumer. Patch at each call site instead.
    """
    instance = MagicMock()
    factory = lambda *a, **kw: instance
    for mod_path in (
        "edgelens_cli.commands.session",
        "edgelens_cli.commands.device",
    ):
        mod = __import__(mod_path, fromlist=["build_client"])
        monkeypatch.setattr(mod, "build_client", factory)
    return instance


def test_session_create_sets_current_and_emits_payload(monkeypatch: pytest.MonkeyPatch):
    client = _patch_client(monkeypatch)
    fake_session = MagicMock()
    fake_session.id = "sess_new"
    fake_session.status.value = "ready"
    fake_session.expires_at = None
    fake_session._connection = None
    fake_session.wait_ready.return_value = fake_session
    client.create_session.return_value = fake_session

    state_mod.save_config(state_mod.Config(api_key="el_test_k"))
    r = _runner().invoke(
        cli, ["session", "create", "--device", "recamera-2002", "--os", "stock-os", "--no-wait"],
    )
    assert r.exit_code == 0, r.output
    assert "sess_new" in r.output
    assert state_mod.load_state().current_session_id == "sess_new"


def test_session_get_resolves_current(monkeypatch: pytest.MonkeyPatch):
    state_mod.save_config(state_mod.Config(api_key="k"))
    state_mod.set_current_session("sess_cur")
    client = _patch_client(monkeypatch)
    fake_session = MagicMock()
    fake_session.id = "sess_cur"
    fake_session.status.value = "ready"
    fake_session.expires_at = None
    fake_session._connection = None
    client.get_session.return_value = fake_session

    r = _runner().invoke(cli, ["session", "get"])
    assert r.exit_code == 0, r.output
    client.get_session.assert_called_once_with("sess_cur")
    assert "sess_cur" in r.output


def test_session_release_clears_current_when_match(monkeypatch: pytest.MonkeyPatch):
    state_mod.save_config(state_mod.Config(api_key="k"))
    state_mod.set_current_session("sess_drop")
    client = _patch_client(monkeypatch)
    fake_session = MagicMock()
    client.get_session.return_value = fake_session

    r = _runner().invoke(cli, ["session", "release"])
    assert r.exit_code == 0, r.output
    fake_session.release.assert_called_once()
    assert state_mod.load_state().current_session_id is None


def test_session_release_keeps_current_when_releasing_other(monkeypatch: pytest.MonkeyPatch):
    state_mod.save_config(state_mod.Config(api_key="k"))
    state_mod.set_current_session("sess_keep")
    client = _patch_client(monkeypatch)
    fake_session = MagicMock()
    client.get_session.return_value = fake_session

    r = _runner().invoke(cli, ["session", "release", "sess_other"])
    assert r.exit_code == 0, r.output
    assert state_mod.load_state().current_session_id == "sess_keep"


# ---- session list ----------------------------------------------------------


def test_session_list_shows_local_state():
    state_mod.set_current_session("sess_a")
    state_mod.set_current_session("sess_b")
    r = _runner().invoke(cli, ["session", "list"])
    assert r.exit_code == 0
    assert "sess_b (current)" in r.output
    assert "sess_a" in r.output


# ---- device exec / deploy / info / ssh -------------------------------------


def _patch_ready_session(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    state_mod.save_config(state_mod.Config(api_key="k"))
    state_mod.set_current_session("sess_ready")
    client = _patch_client(monkeypatch)
    session = MagicMock()
    session.status.value = "ready"
    client.get_session.return_value = session
    return session


def test_exec_prints_stdout_and_propagates_exit_code(monkeypatch: pytest.MonkeyPatch):
    session = _patch_ready_session(monkeypatch)
    session.device.exec.return_value = MagicMock(stdout="hello\n", stderr="", exit_code=0)

    r = _runner().invoke(cli, ["exec", "echo hello"])
    assert r.exit_code == 0
    assert "hello" in r.output


def test_exec_propagates_nonzero_exit(monkeypatch: pytest.MonkeyPatch):
    session = _patch_ready_session(monkeypatch)
    session.device.exec.return_value = MagicMock(stdout="", stderr="boom\n", exit_code=17)

    r = _runner().invoke(cli, ["exec", "false"])
    assert r.exit_code == 17


def test_exec_requires_ready_session(monkeypatch: pytest.MonkeyPatch):
    state_mod.save_config(state_mod.Config(api_key="k"))
    state_mod.set_current_session("sess_flashing")
    client = _patch_client(monkeypatch)
    session = MagicMock()
    session.status.value = "flashing"
    client.get_session.return_value = session

    r = _runner().invoke(cli, ["exec", "ls"])
    assert r.exit_code == 2
    assert "not ready" in r.output


def test_ssh_emits_connection_line(monkeypatch: pytest.MonkeyPatch):
    session = _patch_ready_session(monkeypatch)
    creds = MagicMock(user="recamera", host="192.0.2.42", port=30007, password="pw")
    session.device.ssh.return_value = creds

    r = _runner().invoke(cli, ["ssh"])
    assert r.exit_code == 0
    assert "ssh -p 30007 recamera@192.0.2.42" in r.output


def test_ssh_masks_password_by_default(monkeypatch: pytest.MonkeyPatch):
    """Password is hidden in human mode
    by default."""
    monkeypatch.delenv("EDGELENS_SHOW_PASSWORD", raising=False)
    session = _patch_ready_session(monkeypatch)
    creds = MagicMock(user="recamera", host="10.0.0.1", port=22, password="hunter2")
    session.device.ssh.return_value = creds

    r = _runner().invoke(cli, ["ssh"])
    assert r.exit_code == 0
    assert "hunter2" not in r.output
    assert "<hidden" in r.output


def test_ssh_show_password_flag_reveals(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EDGELENS_SHOW_PASSWORD", raising=False)
    session = _patch_ready_session(monkeypatch)
    creds = MagicMock(user="recamera", host="10.0.0.1", port=22, password="hunter2")
    session.device.ssh.return_value = creds

    r = _runner().invoke(cli, ["ssh", "--show-password"])
    assert r.exit_code == 0
    assert "hunter2" in r.output


def test_ssh_env_reveals(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDGELENS_SHOW_PASSWORD", "1")
    session = _patch_ready_session(monkeypatch)
    creds = MagicMock(user="recamera", host="10.0.0.1", port=22, password="hunter2")
    session.device.ssh.return_value = creds

    r = _runner().invoke(cli, ["ssh"])
    assert r.exit_code == 0
    assert "hunter2" in r.output


def test_ssh_json_mode_omits_password_by_default(monkeypatch: pytest.MonkeyPatch):
    """The JSON output must NOT include the password unless reveal is on."""
    monkeypatch.delenv("EDGELENS_SHOW_PASSWORD", raising=False)
    session = _patch_ready_session(monkeypatch)
    creds = MagicMock(user="recamera", host="10.0.0.1", port=22, password="hunter2")
    session.device.ssh.return_value = creds

    r = _runner().invoke(cli, ["--json", "ssh"])
    assert r.exit_code == 0
    assert "hunter2" not in r.output
    # The JSON should still carry user/host/port.
    assert "recamera" in r.output


# ---- inference + display ---------------------------------------------------


def test_inference_run_emits_stats(monkeypatch: pytest.MonkeyPatch):
    session = _patch_ready_session(monkeypatch)
    stats = MagicMock()
    stats.duration_s = 30
    stats.total_frames = 450
    stats.fps.avg = 15.2
    stats.fps.p95 = 14.9
    stats.latency_ms.p95 = 70.0
    stats.model_dump = lambda: {
        "duration_s": 30, "total_frames": 450,
        "fps": {"avg": 15.2, "p95": 14.9},
        "latency_ms": {"p95": 70.0},
    }
    session.device.inference.run.return_value = stats

    r = _runner().invoke(cli, ["inference", "run", "--duration", "30"])
    assert r.exit_code == 0
    assert "fps avg:      15.20" in r.output


def test_display_play_calls_through(monkeypatch: pytest.MonkeyPatch):
    session = _patch_ready_session(monkeypatch)

    r = _runner().invoke(cli, ["display", "play", "https://x.com/v.mp4", "--loop"])
    assert r.exit_code == 0
    session.device.display.play.assert_called_once_with("https://x.com/v.mp4", loop=True)
    assert "playing" in r.output


# ---- auth missing ---------------------------------------------------------


def test_missing_api_key_is_friendly():
    r = _runner().invoke(cli, ["session", "list"])
    # session list reads local state only — should succeed without auth
    assert r.exit_code == 0

    r2 = _runner().invoke(cli, ["session", "get", "sess_x"])
    assert r2.exit_code != 0
    assert "No API key" in r2.output or "api_key" in r2.output.lower()
