# EdgeLens SDK

Client libraries, test framework integrations, and tooling for the [EdgeLens](https://edgelens.ai) Edge AI Device Farm.

Test your edge AI models on real hardware from your existing test framework — pytest, Playwright, k6, Robot Framework — or from CI/CD pipelines.

## Repository Layout

This is a monorepo. Each subdirectory is a separately-published package.

```
edgelens-sdk/
├── core/                # Shared client libraries
│   ├── python/          # edgelens (PyPI)
│   └── typescript/      # @edgelens/core (npm)
├── integrations/        # Test framework adapters
│   ├── pytest/          # pytest-edgelens (PyPI)
│   ├── playwright/      # @edgelens/playwright-plugin (npm)
│   ├── k6/              # xk6-edgelens (GitHub releases)
│   ├── robot/           # robotframework-edgelens (PyPI)
│   ├── cli/             # edgelens CLI (PyPI)
│   └── mcp/             # edgelens-mcp (PyPI)
├── ci/                  # CI/CD artifacts
│   ├── docker/          # edgelensai/edgelens-sdk (Docker Hub)
│   ├── github-action/   # GitHub Action (used from this repo)
│   └── gitlab/          # GitLab CI templates
├── examples/            # Working example projects per integration
│   ├── pytest/
│   ├── playwright/
│   ├── k6/
│   ├── robot/
│   ├── mlflow/
│   └── wandb/
├── skills/              # LLM integration assets
│   ├── claude-code/     # Claude Code skill file
│   ├── cursor/          # Cursor IDE rules
│   ├── copilot/         # GitHub Copilot instructions
│   └── prompts/         # Generic LLM system prompts
└── docs/                # SDK documentation
```

## Packages

| Package | Registry | Install |
|---|---|---|
| `edgelens-sdk` | PyPI | `pip install edgelens-sdk` |
| `pytest-edgelens` | PyPI | `pip install pytest-edgelens` |
| `robotframework-edgelens` | PyPI | `pip install robotframework-edgelens` |
| `edgelens-cli` | PyPI | `pip install edgelens-cli` |
| `edgelens-mcp` | PyPI | `pip install edgelens-mcp` |
| `@edgelens/core` | npm | `npm install @edgelens/core` |
| `@edgelens/playwright-plugin` | npm | `npm install @edgelens/playwright-plugin` |
| `xk6-edgelens` | GitHub releases | `xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6` |
| `edgelensai/edgelens-sdk` | Docker Hub | `docker pull edgelensai/edgelens-sdk:0.1.1` |
| GitHub Action | GitHub | `uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.1.1` |

## Quick Start

```bash
pip install pytest-edgelens
export EDGELENS_API_KEY=your_key_here
pytest tests/
```

See [examples/](./examples/) for complete working test projects.

## Development

Releasing: see [RELEASING.md](./RELEASING.md).

This monorepo uses per-package tooling — each package has its own build, test, and lint setup. See each subdirectory's README for development instructions.

## License

MIT
