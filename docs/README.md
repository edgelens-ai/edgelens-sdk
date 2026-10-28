# EdgeLens SDK Documentation

Customer-facing documentation for the EdgeLens Edge AI Device Farm.

## Start here

- **[Getting started](./getting-started.md)** — sign up, mint an API key, run your first test in under five minutes.
- **[API reference](./api-reference.md)** — every HTTP endpoint, request/response shape, error semantics.
- **[Security](./security.md)** — API key handling, session isolation, wipe-on-release, and the EdgeLens compatibility hook.

## Framework guides

Pick the one you already use; you do not need to change runners to use EdgeLens.

- **[pytest](./frameworks/pytest.md)** — `pytest-edgelens` plugin, fixtures, OS markers, scopes.
- **[Playwright](./frameworks/playwright.md)** — `@edgelens/playwright-plugin`, browser + device tests.
- **[k6](./frameworks/k6.md)** — `xk6-edgelens` extension, sustained-load benchmarks, thresholds.
- **[Robot Framework](./frameworks/robot.md)** — `robotframework-edgelens`, keyword-driven tests.

## CI/CD

- **[GitHub Actions](./ci-cd/github-actions.md)** — the `edgelens-ai/edgelens-sdk/ci/github-action` action plus self-hosted recipes.
- **[GitLab CI](./ci-cd/gitlab-ci.md)** — `.gitlab-ci.yml` templates from `ci/gitlab/`.

## Experiment tracking

EdgeLens emits per-session metrics; pipe them anywhere.

- **[MLflow](./experiment-tracking/mlflow.md)** — log inference runs as experiment trials.
- **[Weights & Biases](./experiment-tracking/wandb.md)** — stream metrics in real time.

## LLM integration

- **[LLM & MCP integration](./llm-integration.md)** — Claude Code, Cursor, Copilot skill files; the `edgelens-mcp` server for LLMs that drive sessions directly.

## Examples

Each guide above links to a working project in [`examples/`](../examples/). Every example is copy-pasteable — clone the repo, set `EDGELENS_API_KEY`, and the test runs.
