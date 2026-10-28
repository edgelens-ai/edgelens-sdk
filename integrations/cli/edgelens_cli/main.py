"""CLI entry point.

The top-level group exposes a `--json` flag so every command can emit
machine-readable output. Subcommands fan out:

  edgelens login                            save credentials
  edgelens session ...                      create / get / wait / release / list
  edgelens use SESSION_ID                   set current session for follow-up commands
  edgelens exec / deploy / info / ssh       device operations on the current session
  edgelens display ...                      display control
  edgelens inference ...                    inference control
"""

from __future__ import annotations

import sys
from typing import Optional

import click

from edgelens_cli import __version__
from edgelens_cli.commands import device, display, inference, session
from edgelens_cli.output import emit, error
from edgelens_cli.state import Config, clear_current_session, save_config, set_current_session


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="edgelens")
@click.option(
    "--json", "json_mode", is_flag=True, default=False,
    help="Emit machine-readable JSON on stdout.",
)
@click.option(
    "--api-key",
    envvar="EDGELENS_API_KEY",
    help=(
        "Override the API key. Default reads EDGELENS_API_KEY or "
        "~/.edgelens/config.json. Prefer EDGELENS_API_KEY: a key on the "
        "command line is visible in the process list and shell history."
    ),
)
@click.option(
    "--base-url",
    envvar="EDGELENS_BASE_URL",
    help="Override the platform API base URL.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    json_mode: bool,
    api_key: Optional[str],
    base_url: Optional[str],
) -> None:
    """edgelens — drive remote AI cameras from the command line."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode
    ctx.obj["api_key"] = api_key
    ctx.obj["base_url"] = base_url


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _read_api_key() -> str:
    if _stdin_is_tty():
        return click.prompt("API key", hide_input=True)
    return sys.stdin.readline()


@cli.command()
@click.option(
    "--api-key", default=None,
    help=(
        "API key to persist. Omit it to be prompted (input hidden) or to "
        "pipe the key on stdin. Prefer that: a key on the command line is "
        "visible in the process list and shell history."
    ),
)
@click.option("--base-url", default=None, help="Optional platform base URL.")
@click.pass_context
def login(ctx: click.Context, api_key: Optional[str], base_url: Optional[str]) -> None:
    """Persist credentials to ~/.edgelens/config.json (chmod 0600).

    The key is read from a hidden prompt, or from stdin when stdin is not
    a terminal.
    """
    if api_key is None:
        api_key = _read_api_key().strip()
    if not api_key:
        error("no API key given", exit_code=2)
    save_config(Config(api_key=api_key, base_url=base_url))
    emit(
        {"saved": True, "config_path": "~/.edgelens/config.json"},
        json_mode=ctx.obj["json_mode"],
        human="✓ credentials saved to ~/.edgelens/config.json",
    )


@cli.command()
@click.pass_context
def logout(ctx: click.Context) -> None:
    """Forget credentials + current session pointer."""
    save_config(Config())
    clear_current_session()
    emit(
        {"cleared": True},
        json_mode=ctx.obj["json_mode"],
        human="✓ cleared ~/.edgelens/config.json and ~/.edgelens/state.json",
    )


@cli.command()
@click.argument("session_id")
@click.pass_context
def use(ctx: click.Context, session_id: str) -> None:
    """Set the current session for follow-up commands (exec, deploy, ...)."""
    if not session_id.startswith("sess_"):
        error("session ids start with 'sess_'", exit_code=2)
    set_current_session(session_id)
    emit(
        {"current_session_id": session_id},
        json_mode=ctx.obj["json_mode"],
        human=f"✓ current session set to {session_id}",
    )


cli.add_command(session.session_group)
cli.add_command(device.exec_cmd)
cli.add_command(device.deploy_cmd)
cli.add_command(device.info_cmd)
cli.add_command(device.ssh_cmd)
cli.add_command(display.display_group)
cli.add_command(inference.inference_group)


if __name__ == "__main__":
    cli()
