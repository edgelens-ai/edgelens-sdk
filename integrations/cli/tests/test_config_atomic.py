"""Config file written with atomic 0o600."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from edgelens_cli import state


def test_config_file_is_0o600(tmp_path: Path, monkeypatch):
    """The file must be 0o600 from the moment it exists — no TOCTOU
    window between create and chmod."""
    monkeypatch.setattr(state, "CONFIG_PATH", tmp_path / "config.json")

    state.save_config(state.Config(api_key="el_test_secret"))
    cfg_path = tmp_path / "config.json"
    assert cfg_path.exists()
    mode = stat.S_IMODE(os.stat(cfg_path).st_mode)
    assert mode == 0o600


def test_config_overwrite_preserves_0o600(tmp_path: Path, monkeypatch):
    """Successive writes don't broaden the perms."""
    monkeypatch.setattr(state, "CONFIG_PATH", tmp_path / "config.json")
    state.save_config(state.Config(api_key="el_test_first"))
    state.save_config(state.Config(api_key="el_test_second"))
    mode = stat.S_IMODE(os.stat(tmp_path / "config.json").st_mode)
    assert mode == 0o600


def test_config_contents_correct(tmp_path: Path, monkeypatch):
    """Behavior preserved: the JSON body is still what callers expect."""
    monkeypatch.setattr(state, "CONFIG_PATH", tmp_path / "config.json")
    state.save_config(state.Config(api_key="el_test_k", base_url="https://x"))
    data = json.loads((tmp_path / "config.json").read_text())
    assert data == {"api_key": "el_test_k", "base_url": "https://x"}


def test_existing_loose_config_is_tightened(tmp_path: Path, monkeypatch):
    """open(O_CREAT, 0o600) leaves an existing file's mode alone, so a
    config.json that is already 0o644 must be tightened on write, before the
    key goes into it."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}")
    os.chmod(cfg_path, 0o644)
    monkeypatch.setattr(state, "CONFIG_PATH", cfg_path)

    state.save_config(state.Config(api_key="el_test_secret"))

    assert stat.S_IMODE(os.stat(cfg_path).st_mode) == 0o600
    assert json.loads(cfg_path.read_text())["api_key"] == "el_test_secret"


def test_existing_loose_state_is_tightened(tmp_path: Path, monkeypatch):
    st_path = tmp_path / "state.json"
    st_path.write_text("{}")
    os.chmod(st_path, 0o666)
    monkeypatch.setattr(state, "STATE_PATH", st_path)

    state.save_state(state.State(current_session_id="sess_1"))

    assert stat.S_IMODE(os.stat(st_path).st_mode) == 0o600


def test_config_write_refuses_symlink(tmp_path: Path, monkeypatch):
    """A symlink planted at config.json must not redirect the key."""
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    link = tmp_path / "config.json"
    link.symlink_to(target)
    monkeypatch.setattr(state, "CONFIG_PATH", link)

    with pytest.raises(OSError):
        state.save_config(state.Config(api_key="el_test_secret"))
    assert "el_test_secret" not in target.read_text()


def test_new_config_dir_is_owner_only(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / "fresh" / ".edgelens"
    monkeypatch.setattr(state, "CONFIG_PATH", cfg_dir / "config.json")
    state.save_config(state.Config(api_key="el_test_secret"))
    assert stat.S_IMODE(os.stat(cfg_dir).st_mode) == 0o700
