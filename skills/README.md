# LLM Skills

Skill definitions and integrations that teach LLMs how to use the
EdgeLens SDK to write tests against real edge-AI hardware.

| Subdir | Target | Status |
|---|---|---|
| `claude-code/` | `CLAUDE.md` skill for Claude Code | Done — paired MCP server ships in `integrations/mcp/` (scaffold) |
| `cursor/` | `.cursorrules` for Cursor IDE | Done |
| `copilot/` | `.github/copilot-instructions.md` for GitHub Copilot | Done |
| `prompts/` | Generic LLM system prompt | Done |

## How to install in a consumer project

Each file is meant to be **copied** into the consumer repo at the
path its tooling expects:

```bash
# Claude Code
cp claude-code/CLAUDE.md /path/to/consumer/CLAUDE.md

# Cursor
cp cursor/.cursorrules /path/to/consumer/.cursorrules

# GitHub Copilot
mkdir -p /path/to/consumer/.github
cp copilot/.github/copilot-instructions.md \
    /path/to/consumer/.github/copilot-instructions.md

# Generic LLM (paste into your own system prompt)
cat prompts/edgelens-system-prompt.md
```

All four files cover the same SDK surface — pick the ones for the
tools the team uses. They agree on patterns, anti-patterns, and the
SDK enum semantics so an LLM swapped between tools doesn't get
contradictory advice.
