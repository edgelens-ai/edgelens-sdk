"""Common client-construction wrapper for every command.

Resolves API key from (in priority order):
- ``--api-key`` flag on the command
- ``EDGELENS_API_KEY`` env var
- ``~/.edgelens/config.json``

Same for ``--base-url``.

Raises a friendly click error instead of letting an
``AuthenticationError`` bubble.
"""

from __future__ import annotations

from typing import Optional

import click
from edgelens import EdgeLensClient
from edgelens.errors import AuthenticationError

from edgelens_cli.state import load_config


def build_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> EdgeLensClient:
    config = load_config()
    effective_key = api_key or config.api_key
    effective_url = base_url or config.base_url
    if not effective_key:
        raise click.ClickException(
            "No API key. Set EDGELENS_API_KEY or run `edgelens login`."
        )
    kwargs: dict = {"api_key": effective_key}
    if effective_url:
        kwargs["base_url"] = effective_url
    try:
        return EdgeLensClient(**kwargs)
    except AuthenticationError as e:
        raise click.ClickException(str(e))
