"""Output helpers — human vs JSON modes."""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

import click


def emit(payload: Any, *, json_mode: bool, human: Optional[str] = None) -> None:
    """Emit ``payload`` as JSON or as the supplied ``human`` string.

    When ``json_mode`` is True, the JSON form goes to stdout
    regardless of ``human``. When False and ``human`` is None, we
    fall back to ``str(payload)``.
    """
    if json_mode:
        click.echo(json.dumps(payload, indent=2, default=_default))
        return
    click.echo(human if human is not None else str(payload))


def warn(msg: str) -> None:
    click.echo(click.style(f"warning: {msg}", fg="yellow"), err=True)


def error(msg: str, *, exit_code: int = 1) -> None:
    click.echo(click.style(f"error: {msg}", fg="red"), err=True)
    sys.exit(exit_code)


def _default(o: Any) -> Any:
    # pydantic v2 models expose model_dump
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if hasattr(o, "__dict__"):
        return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
    return str(o)
