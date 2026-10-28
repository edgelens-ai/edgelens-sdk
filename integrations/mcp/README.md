# edgelens-mcp

Model Context Protocol server that exposes the EdgeLens SDK as LLM tools. Drop
into Claude Desktop, Claude Code, Cursor, or any other MCP host and the LLM can
allocate cameras, deploy models, run inference, and SSH the device directly.

## Install

```sh
pip install edgelens-mcp
# or, with uv:
uv tool install edgelens-mcp
```

Adds an `edgelens-mcp` command to your PATH.

## Claude Desktop

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`,
Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "edgelens": {
      "command": "edgelens-mcp",
      "env": {
        "EDGELENS_API_KEY": "el_test_yourkey"
      }
    }
  }
}
```

Restart Claude Desktop. The hammer icon shows the EdgeLens tools.

## Claude Code

Add to `~/.claude/mcp.json` (or project-local `.mcp.json`):

```json
{
  "mcpServers": {
    "edgelens": {
      "command": "edgelens-mcp",
      "env": {
        "EDGELENS_API_KEY": "el_test_yourkey"
      }
    }
  }
}
```

## Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "edgelens": {
      "command": "edgelens-mcp",
      "env": {
        "EDGELENS_API_KEY": "el_test_yourkey"
      }
    }
  }
}
```

## Tools

Once connected, the host gets these tools (same surface as the SDK and CLI):

### Session lifecycle

| Tool | What |
|---|---|
| `create_session` | Allocate a camera. Defaults to `recamera-2002` / `stock-os` / wait-for-ready. |
| `get_session` | Fetch current state. Defaults to current session. |
| `wait_session_ready` | Block until status=ready. |
| `release_session` | End session, return device to pool. |
| `list_sessions` | Sessions this server has touched (process-local). |

### Device ops

| Tool | What |
|---|---|
| `exec_command` | Run a shell command on the camera via SSH. |
| `deploy_model` | Deploy a model + optional config + extra files (local path or URL). |
| `get_ssh_details` | Returns `user/host/port/password` + a ready-to-paste `ssh` command. |
| `get_device_info` | Full device-info report. |

### Display

| Tool | What |
|---|---|
| `display_play` | Play a video on the external display. |
| `display_show` | Show a still image. |
| `display_stop` | Stop playback. |
| `display_status` | Current display state. |

### Inference (stock OS)

| Tool | What |
|---|---|
| `inference_start` / `inference_stop` | Start/stop the inference loop. |
| `inference_once` | Run one frame, return detections. |
| `inference_stats` | Point-in-time snapshot (fps, latency). |
| `inference_run` | Aggregate stats over a duration. |

## Current-session pattern

After `create_session`, follow-up tools default to that session — you don't have
to thread the id through every call. Pass `session_id` explicitly only when
working with multiple concurrent sessions in one conversation.

```
user:    "spin me up a camera"
claude:  → create_session(device_type="recamera-2002", os="stock-os")
         ← {"id": "sess_abc", "status": "ready", "device": {...}}
user:    "what's the kernel version?"
claude:  → exec_command(command="uname -r")
         ← {"stdout": "5.10.10-edgelens", ...}
```

## Environment

| Var | Purpose |
|---|---|
| `EDGELENS_API_KEY` | Required. Pass via the host's `env` block. |
| `EDGELENS_BASE_URL` | Optional. Override the platform API base URL (self-hosted). |

## Transport

This server speaks **stdio** — the MCP host spawns it as a subprocess.

A hosted streamable-HTTP variant (for remote-MCP integrations like claude.ai
web) is planned. Same tool code, different transport — see the roadmap.

## Develop

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e "../../core/python"   # editable SDK core (not yet on PyPI)
pip install -e ".[dev]"
pytest
```

The `mcp` dependency is pinned `<2` (2.x renamed `FastMCP` → `MCPServer`).
The tests call each tool function directly (FastMCP's `@mcp.tool()`
returns the function unchanged) and read tool annotations from
`server.mcp._tool_manager`.

If your environment can't reach PyPI, run the suite in a container:

```sh
docker run --rm -e HOME=/tmp -v "$PWD/../..:/sdk:ro" python:3.11-slim sh -c '
  cd /tmp && cp -r /sdk/core/python core && cp -r /sdk/integrations/mcp mcp
  rm -rf core/.venv mcp/.venv && python -m venv v && . v/bin/activate
  pip install -q "mcp[cli]>=1.2,<2" pytest pytest-asyncio && pip install -q ./core ./mcp
  python -m pytest mcp/tests -q'
```

Pairs with the [Python SDK](../../core/python), [CLI](../cli), and
[pytest plugin](../pytest).
