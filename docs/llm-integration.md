# LLM & MCP Integration

EdgeLens ships two complementary LLM surfaces:

1. **Skill files** — tell an LLM how to *write* EdgeLens tests in your
   editor.
2. **MCP server** (`edgelens-mcp`) — let an LLM *drive* EdgeLens
   sessions directly as tool calls.

Use both together: the skill teaches the LLM the right shape; the MCP
server lets it execute the test it just wrote.

## Skill files

Live under [`skills/`](../skills/). Each is a copy-paste:

| Target | File | Copy to |
|---|---|---|
| Claude Code | `skills/claude-code/CLAUDE.md` | `CLAUDE.md` at repo root |
| Cursor | `skills/cursor/.cursorrules` | `.cursorrules` at repo root |
| GitHub Copilot | `skills/copilot/.github/copilot-instructions.md` | `.github/copilot-instructions.md` |
| Generic LLM | `skills/prompts/edgelens-system-prompt.md` | paste into the LLM's system prompt |

All four cover the same surface so an LLM swapped between tools
doesn't get contradictory advice. They include the SDK shape, OS tier
semantics (`"stock-os"` / `"recamagined"`), the framework-native
principle, decision rules, anti-patterns, and a failure-mode triage
table.

## MCP server

The `edgelens-mcp` server (Model Context Protocol) exposes the SDK
surface as tool calls an LLM can invoke directly. Add it to your
LLM's MCP config:

```json
{
  "mcpServers": {
    "edgelens": {
      "command": "edgelens-mcp",
      "env": { "EDGELENS_API_KEY": "el_live_xxx" }
    }
  }
}
```

The exposed tools mirror the SDK:

| Tool | What |
|---|---|
| `create_session` | Allocate a device. |
| `wait_ready` | Block until `status=ready`. |
| `release_session` | Release. |
| `deploy_model` | Upload a local model file (plus optional config and extra files) to the device. |
| `inference_run` | Run inference for N seconds; return stats. |
| `inference_stats` | One snapshot of fps + latency. |
| `display_play` / `show` / `stop` | Display control. |
| `exec` | Shell command via SSH. |
| `device_info` | Hostname / hardware / OS version. |
| `list_sessions` | What's currently allocated to this key. |

The MCP server reads `EDGELENS_API_KEY` from its environment — it does
not receive the key from the LLM, so the LLM can't accidentally leak
it back to the user.

The server lives in [`integrations/mcp/`](../integrations/mcp/) and is
published as `edgelens-mcp` (Python 3.10+).

## When to use the skill vs the MCP server

**Skill (no execution).** The LLM helps you write a test you'll commit
and run yourself in CI. No tokens are spent on hardware. This is the
default — you want the LLM to be a coding pair, not a runtime.

**MCP server (with execution).** The LLM allocates devices, runs
inference, and reads back stats. Useful for:
- Interactive exploration ("what's the p95 latency at confidence_threshold=0.5?").
- Letting the LLM verify a test it just wrote actually passes.
- Agentic workflows where the LLM picks the next model to deploy based on the previous result.

**Both.** Install the skill in the editor so generated tests are
correct; enable MCP for the interactive moments. The skill content
includes guardrails the MCP server itself doesn't enforce — anti-patterns,
acceptance-criteria discipline — so even in MCP mode the skill is what
keeps the LLM's choices reasonable.

## Anti-patterns

The skill files spell these out, but worth flagging here:

- LLM-generated `time.sleep(N)` to wait for ready. Use `session.wait_ready()`.
- LLM-generated `os="stock"`. The value is `"stock-os"`.
- Mocked `EdgeLensClient` on a hardware test. Defeats the point of EdgeLens; mock at the model boundary instead.
- `try/except: pass` around EdgeLens errors. Always surface them.

If you see an LLM produce any of the above, the skill file isn't installed
or isn't being loaded — check the editor's skill-loading behavior.
