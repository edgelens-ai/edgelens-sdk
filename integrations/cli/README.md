# edgelens-cli

Command-line interface for the EdgeLens Edge AI Device Farm. Drives the
same `EdgeLensClient` as the Python SDK; useful for ad-hoc sessions,
quick experiments, and shell scripts.

## Install

```sh
pip install edgelens-cli
# or
pipx install edgelens-cli
```

Adds an `edgelens` executable to your PATH.

## Quickstart

```sh
edgelens login --api-key el_test_yourkey
edgelens session create --device recamera-2002 --os stock-os --timeout 600
# session id is remembered as 'current' — follow-up commands target it
edgelens info
edgelens exec 'uname -a'
edgelens deploy ./face.cvimodel
edgelens inference run --duration 30
edgelens session release
```

`--json` on the root command emits machine-readable JSON on every call,
useful for shell pipelines or CI:

```sh
edgelens --json session create --no-wait | jq -r .id
```

## Commands

```
edgelens login                            persist credentials (~/.edgelens/config.json)
edgelens logout                           forget credentials + current-session pointer
edgelens use <SESSION_ID>                 set current session for follow-up commands

edgelens session create [--device --os --timeout --wait/--no-wait]
edgelens session get [SESSION_ID]         defaults to current
edgelens session wait [SESSION_ID]        block until status=ready
edgelens session release [SESSION_ID]
edgelens session list                     recent sessions (from local state)

edgelens exec '<command>'                 run via SSH (proxied)
edgelens deploy <model_path> [--config --file ...]
edgelens info                             device info report
edgelens ssh                              print SSH connection details

edgelens display play <url> [--loop]
edgelens display show <url>
edgelens display stop
edgelens display status

edgelens inference start
edgelens inference stop
edgelens inference once
edgelens inference stats
edgelens inference run [--duration N --collect-frames]
```

## Configuration

| Source | Used for |
|---|---|
| `--api-key`, `--base-url` flags | One-off overrides |
| `EDGELENS_API_KEY`, `EDGELENS_BASE_URL` env vars | Shell-session-scoped |
| `~/.edgelens/config.json` (chmod 0600) | Persistent default — set via `edgelens login` |

Current-session state lives at `~/.edgelens/state.json` (chmod 0600).
Session ids touched in the last ten commands are kept under `recent`
so `edgelens session list` shows what you were doing.

## Develop

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

