# GitHub Actions

`edgelens-ai/edgelens-sdk/ci/github-action` runs your EdgeLens-backed test suite as a step
in your workflow. It wraps the SDK setup so you don't write the same
six lines in every workflow.

## Quickstart

```yaml
# .github/workflows/edgelens.yml
name: EdgeLens hardware tests

on:
  pull_request:
    branches: [main]

jobs:
  hardware:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
        with:
          api-key: ${{ secrets.EDGELENS_API_KEY }}
          command: pytest tests/hardware/ --junit-xml=junit.xml
```

Add `EDGELENS_API_KEY` to your repository secrets first
(Settings → Secrets and variables → Actions → New repository secret).

## Action inputs

| Input | Default | Purpose |
|---|---|---|
| `api-key` | — | **Required.** EdgeLens API key. Pass via a secret, never in YAML. |
| `command` | `pytest` | Test command to run inside the container. |
| `image` | `edgelensai/edgelens-sdk:0.2.0` | Docker image to run the test command in. The default is a pinned tag; pin a version and digest in your own workflow. |
| `working-directory` | `.` | Repo-relative directory to run the command from. |
| `artifacts-path` | `test-results,playwright-report,coverage,junit.xml` | Comma-separated globs of test artifacts to upload. Empty disables upload. |
| `artifacts-retention-days` | `14` | Days to retain uploaded artifacts. |
| `junit-file` | `junit.xml` | Path to a JUnit XML file used to compute the summary. Optional; falls back to exit code. |
| `comment-on-pr` | `true` | Post a summary comment on the PR. No-op outside `pull_request` events. |
| `base-url` | `""` | Override the EdgeLens platform API base URL (self-hosted deployments). |
| `extra-env` | `""` | Multiline `KEY=value` pairs to inject into the container env. |

## Matrix builds (one job per OS)

```yaml
strategy:
  matrix:
    os: [stock-os, recamagined]
steps:
  - uses: actions/checkout@v4
  - uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
    with:
      api-key: ${{ secrets.EDGELENS_API_KEY }}
      command: pytest tests/hardware/ --edgelens-os=${{ matrix.os }} --junit-xml=junit.xml
```

EdgeLens enforces `max_concurrent_sessions` per key — matrix jobs run
in parallel from GitHub's side, but they queue on the EdgeLens side if
the cap is reached. Portal-minted keys allow one concurrent session,
and the portal has no control to change that yet; size the matrix to
the key's cap.

## Without the action (direct invocation)

If you need finer control, install the SDK yourself:

```yaml
- env:
    EDGELENS_API_KEY: ${{ secrets.EDGELENS_API_KEY }}
  run: |
    pip install pytest-edgelens
    pytest tests/hardware/ --edgelens-os=stock-os
```

The plugin reads the key from `EDGELENS_API_KEY`. Do not pass it with
`--edgelens-key`: a value on the command line shows up in the process
list and in the generated step script.

This is the right move when you want to:
- Run two frameworks in one job.
- Pass framework-specific flags the action doesn't expose.
- Reuse your project's existing pytest invocation verbatim.

## Caching the SDK install

EdgeLens installs are small — the cache hit-rate payoff is marginal —
but if you do many parallel jobs:

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.12"
    cache: pip
```

For Node-based runners:

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: "20"
    cache: npm
```

## Failure triage

The action exits non-zero whenever the framework runner does. Look at:

- **Step log** — pytest / Playwright / k6 output, exactly what you'd
  see locally.
- **Session id in the log** — every test logs the session it allocated.
  Look it up in the portal for the session's history.

Common failure → cause mapping:

| Output snippet | Likely cause |
|---|---|
| `AuthenticationError: 401 Invalid API key` | Secret missing / wrong / revoked. |
| `TimeoutError: status never reached ready` | The session did not reach `ready` within its server-side deadline. Read the session's `error` field (`GET /v1/sessions/{id}`). |
| `429 max_concurrent_sessions` | Matrix is too wide for the key's cap. |

## Self-hosted runners

Set `base-url` to point at your self-hosted EdgeLens deployment:

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    base-url: https://edgelens.internal.corp
    command: pytest tests/hardware/ --junit-xml=junit.xml
```

The action is otherwise identical.
