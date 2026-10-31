"""Persistent CLI state (api key, current session) at ``~/.edgelens/``.

The state is split:

- ``~/.edgelens/config.json`` — auth + base URL. Written by ``edgelens login``.
- ``~/.edgelens/state.json``  — current-session pointer + recent sessions.
  Written by ``edgelens session create`` / ``edgelens use``.

Both files have ``0o600`` permissions; absence of either is treated as
empty.
"""

from __future__ import annotations

import errno
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


DEFAULT_DIR = Path.home() / ".edgelens"
CONFIG_PATH = DEFAULT_DIR / "config.json"
STATE_PATH = DEFAULT_DIR / "state.json"


def _mask(api_key: Optional[str]) -> str:
    """Say whether a key is set, and nothing else about it.

    Any value derived from the key, a prefix or a digest alike, lets
    whoever reads the output confirm a guessed key offline.
    """
    return "None" if api_key is None else "<set>"


@dataclass
class Config:
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None

    def __repr__(self) -> str:
        # Any traceback carrying a Config reaches the operator's
        # terminal or CI log; `asdict` is unaffected, so what gets
        # persisted to config.json does not change.
        return (
            f"Config(api_key={_mask(self.api_key)}, "
            f"base_url={self.base_url!r})"
        )


@dataclass
class State:
    current_session_id: Optional[str] = None
    recent: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path``, owner-only (0o600) on every write.

    ``os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`` creates a new
    file as 0o600 in one syscall, so there is no window between create
    and chmod in which another user on a multi-user host could read the
    API key. The mode argument only applies when the file is created,
    though: an existing file (copied in, or written by another tool under
    a looser umask) keeps its mode. So the open file is also fchmod-ed to
    0o600 before anything is written into it. O_NOFOLLOW refuses a
    symlink planted at the path. A new parent directory is created 0o700.
    When os.chmod is the only available knob (Windows, overlay FS,
    network shares), emit a clear warning so the operator knows the
    config file may not be owner-restricted.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = json.dumps(data, indent=2)

    try:
        fd = os.open(
            str(path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise
        # Windows / overlay paths where O_CREAT with mode is unsupported.
        # Fall back to write_text + best-effort chmod, but loudly.
        _log.warning(
            "%s: atomic 0o600 create unavailable; falling back to "
            "write_text + chmod (file may end up world-readable on "
            "this platform).", path,
        )
        path.write_text(body)
        try:
            os.chmod(path, 0o600)
        except OSError as chmod_err:
            _log.warning(
                "%s: chmod 0o600 also failed: %s. The API key in this "
                "file may be readable by other local users.", path, chmod_err,
            )
        return

    with os.fdopen(fd, "w") as f:
        if hasattr(os, "fchmod"):
            os.fchmod(f.fileno(), 0o600)
        f.write(body)


def load_config() -> Config:
    """Load ``~/.edgelens/config.json``. ``EDGELENS_*`` env vars override."""
    raw = _read_json(CONFIG_PATH)
    return Config(
        api_key=os.environ.get("EDGELENS_API_KEY") or raw.get("api_key"),
        base_url=os.environ.get("EDGELENS_BASE_URL") or raw.get("base_url"),
    )


def save_config(config: Config) -> None:
    """Write ``~/.edgelens/config.json``. Empty fields are stripped."""
    payload = {k: v for k, v in asdict(config).items() if v is not None}
    _write_json(CONFIG_PATH, payload)


def load_state() -> State:
    raw = _read_json(STATE_PATH)
    return State(
        current_session_id=raw.get("current_session_id"),
        recent=list(raw.get("recent") or []),
    )


def save_state(state: State) -> None:
    _write_json(STATE_PATH, asdict(state))


def set_current_session(session_id: str, *, remember: int = 10) -> None:
    """Mark ``session_id`` as the current session and remember it."""
    state = load_state()
    state.current_session_id = session_id
    if session_id in state.recent:
        state.recent.remove(session_id)
    state.recent.insert(0, session_id)
    state.recent = state.recent[:remember]
    save_state(state)


def clear_current_session() -> None:
    state = load_state()
    state.current_session_id = None
    save_state(state)
