"""Config file written with atomic 0o600."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

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
