"""Resolve a session id from explicit argument or current-session state."""

from __future__ import annotations

from typing import Optional

import click

from edgelens_cli.state import load_state


def resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    state = load_state()
    if state.current_session_id is None:
        raise click.ClickException(
            "No current session. Run `edgelens session create ...` or `edgelens use <id>`."
        )
    return state.current_session_id
