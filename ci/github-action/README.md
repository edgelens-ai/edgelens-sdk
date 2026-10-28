# EdgeLens GitHub Action

Used as `edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0`, a subpath of
this repository.

GitHub Action that runs your EdgeLens test command in the pre-built
[`edgelensai/edgelens-sdk`](../docker) image, uploads artifacts, posts a PR
comment summary, and writes to the Step Summary.

Composite action — works on any GitHub-hosted Linux runner (and any
self-hosted one with `docker` available).

## Quick start

```yaml
# .github/workflows/edgelens-tests.yml
name: EdgeLens tests
on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
        with:
          api-key: ${{ secrets.EDGELENS_API_KEY }}
          command: pytest --junit-xml=junit.xml
```

That's enough for a Python suite. The image has `pytest` + the
`edgelens` SDK + the `edgelens` CLI pre-installed; same for the JS
side via `@edgelens/core` + `@edgelens/playwright-plugin`.

## Examples

### Playwright

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    command: npx playwright test --reporter=junit
```

### Self-hosted EdgeLens

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    base-url: https://edgelens.internal.acme.com
    command: pytest --junit-xml=junit.xml
```

### Extra env into the container

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    command: pytest
    extra-env: |
      MODEL_PATH=./models/face.cvimodel
      EXPECTED_FPS=15
```

### Pin a specific image version

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    image: edgelensai/edgelens-sdk:0.2.0
    command: pytest --junit-xml=junit.xml
```

## Inputs

| Name | Required | Default | Purpose |
|---|---|---|---|
| `api-key` | yes | — | EdgeLens API key. Pass via a secret. |
| `command` | no | `pytest` | Command run inside the container. |
| `image` | no | `edgelensai/edgelens-sdk:0.2.0` | Docker image tag. The default is the image released with this version of the action. |
| `working-directory` | no | `.` | Repo-relative dir to run in. |
| `artifacts-path` | no | `test-results,playwright-report,coverage,junit.xml` | Glob list of artifacts to upload. Empty disables upload. |
| `artifacts-retention-days` | no | `14` | Days to keep uploaded artifacts. |
| `junit-file` | no | `junit.xml` | Path to a JUnit XML report relative to `working-directory`. Optional but unlocks the summary table. |
| `comment-on-pr` | no | `true` | Post a summary comment on the PR. No-op outside `pull_request` events. |
| `base-url` | no | — | Override the platform API base URL. |
| `extra-env` | no | — | Multiline `KEY=value` pairs to inject into the container env. |

## Outputs

| Name | Purpose |
|---|---|
| `passed` | `"true"` if the test command exited 0, `"false"` otherwise. |
| `summary` | Markdown summary, mirrored to `GITHUB_STEP_SUMMARY`. |

## What it does

1. **Pulls the image** so any subsequent step in your job can see it cached.
2. **Runs your command** in a fresh container, mounting `${{ github.workspace }}` at `/workspace`. Env vars: `EDGELENS_API_KEY`, optional `EDGELENS_BASE_URL`, plus anything in `extra-env`.
3. **Summarizes** by parsing the JUnit XML if present. Falls back to exit-code-only if not.
4. **Uploads artifacts** named `edgelens-test-results-<run-attempt>` (skipped if `artifacts-path` is empty).
5. **Comments on the PR** with the summary when `comment-on-pr` is true and the event is `pull_request`.
6. **Fails the step** if the test command exited non-zero. (We don't swallow failures — the artifact + comment side-effects run first via `if: always()`.)

## Versioning

The action is versioned with the rest of this repository: one version
covers the SDK packages, this action and the `edgelensai/edgelens-sdk`
image. Reference the action by its exact release tag, for example
`@v0.1.0`. Release tags are immutable, and there is no moving major-version
tag.

The action's default `image` is the image released with the same version,
`edgelensai/edgelens-sdk:0.2.0` for `@v0.1.0`. To guard against a
re-pushed tag, pin the digest as well through the `image` input.

Depends on the CI image in [`ci/docker/`](../docker).
