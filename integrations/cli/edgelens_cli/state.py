"""Persistent CLI state (api key, current session) at ``~/.edgelens/``.

The state is split:

- ``~/.edgelens/config.json`` — auth + base URL. Written by ``edgelens login``.
- ``~/.edgelens/state.json``  — current-session pointer + recent sessions.
  Written by ``edgelens session create`` / ``edgelens use``.

Both files have ``0o600`` permissions; absence of either is treated as
empty.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


DEFAULT_DIR = Path.home() / ".edgelens"
CONFIG_PATH = DEFAULT_DIR / "config.json"
STATE_PATH = DEFAULT_DIR / "state.json"


def _fingerprint(api_key: Optional[str]) -> str:
    """Render a key so two different keys look different and neither is readable.

    A prefix of a secret is a piece of the secret, so the mask is a
    one-way digest rather than a truncation: six hex characters of
    sha256 identify a key to someone who already holds it and give
    nothing to someone who does not.
    """
    if api_key is None:
        return "None"
    return f"<set sha256:{hashlib.sha256(api_key.encode()).hexdigest()[:6]}>"


@dataclass
class Config:
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None

    def __repr__(self) -> str:
        # Any traceback carrying a Config reaches the operator's
        # terminal or CI log; `asdict` is unaffected, so what gets
        # persisted to config.json does not change.
        return (
            f"Config(api_key={_fingerprint(self.api_key)}, "
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
    """Atomic create with 0o600 in a
    single syscall instead of write-then-chmod.

    Creating the file with default perms and chmod-ing it afterwards
    would leave a TOCTOU window in which another user on a multi-user
    host could read the API key.
    ``os.open(path, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`` creates the
    file with 0o600 atomically, so that window never exists.
    When os.chmod is the only available knob (Windows, overlay FS,
    network shares), emit a clear warning so the operator knows the
    config file may not be owner-restricted.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, indent=2)

    try:
        fd = os.open(
            str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
        )
    except OSError:
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
        except OSError as e:
            _log.warning(
                "%s: chmod 0o600 also failed: %s. The API key in this "
                "file may be readable by other local users.", path, e,
            )
        return

    with os.fdopen(fd, "w") as f:
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
