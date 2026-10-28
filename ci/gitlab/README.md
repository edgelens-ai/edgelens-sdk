# EdgeLens GitLab CI templates

Reusable `.gitlab-ci.yml` templates that run your tests inside the
[`edgelensai/edgelens-sdk`](../docker) image with the standard GitLab sugar:
artifacts surfaced to the UI, JUnit report wired into the merge-
request widget, and pip/npm caches keyed on the branch.

GitLab counterpart to the [GitHub Action](../github-action).

## Quick start

Add to your project's `.gitlab-ci.yml`:

```yaml
include:
  - remote: "https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/main/ci/gitlab/edgelens.gitlab-ci.yml"

stages:
  - test

edgelens-tests:
  stage: test
  extends: .edgelens:pytest
```

Set `EDGELENS_API_KEY` as a **masked + protected** CI/CD variable in
project settings. The template checks it's set and fails fast if not.

## Templates

| Template | What it runs | Notes |
|---|---|---|
| `.edgelens:base` | (override `script`) | The shared scaffolding — image, cache, artifacts, JUnit wiring, API key gate. Extend this when you need a custom command. |
| `.edgelens:pytest` | `pytest --junit-xml=junit.xml` | Default Python suite. |
| `.edgelens:playwright` | `npx playwright test --reporter=junit --output=test-results` | Playwright via `@edgelens/playwright-plugin`. JUnit report at `results.xml`. |
| `.edgelens:robot` | `robot --output output.xml tests/` | Robot Framework (uses the `robotframework-edgelens` lib once it ships). |

## Variables

| Var | Default | Purpose |
|---|---|---|
| `EDGELENS_API_KEY` | — (required) | Mask + protect. |
| `EDGELENS_BASE_URL` | — | Self-hosted deployments. |
| `EDGELENS_IMAGE` | `edgelensai/edgelens-sdk:latest` | Image tag override. Pin in production. |
| `JUNIT_FILE` | `junit.xml` (pytest) / `results.xml` (Playwright) / `output.xml` (Robot) | Path to the JUnit XML report. |

Override on the job:

```yaml
edgelens-tests:
  extends: .edgelens:pytest
  variables:
    EDGELENS_IMAGE: "edgelensai/edgelens-sdk:0.1.1"   # pin
    JUNIT_FILE: "my-report.xml"
```

## Build on `.edgelens:base`

```yaml
my-job:
  extends: .edgelens:base
  script:
    - edgelens session list
    - python my_custom_test.py
```

You inherit:
- The image (`$EDGELENS_IMAGE`)
- The `before_script` API-key check
- `cache:` for `.cache/pip` and `.cache/npm`
- `artifacts:` for `test-results`, `playwright-report`, `coverage`, `$JUNIT_FILE`
- `reports.junit` wired so GitLab surfaces results in the MR widget

## Matrix

```yaml
edgelens-matrix:
  extends: .edgelens:base
  parallel:
    matrix:
      - OS_TARGET: ["stock", "recamagined"]
        SUITE: ["smoke", "full"]
  variables:
    EDGELENS_OS: "$OS_TARGET"
  script:
    - |
      case "$SUITE" in
        smoke) pytest -m smoke --junit-xml=$JUNIT_FILE ;;
        full)  pytest --junit-xml=$JUNIT_FILE ;;
      esac
```

See [`examples/matrix.gitlab-ci.yml`](examples/matrix.gitlab-ci.yml).

## Artifacts

Each job uploads (when present):
- `test-results/` — Playwright video + trace + screenshots
- `playwright-report/` — HTML report
- `coverage/` — coverage report
- `$JUNIT_FILE` — JUnit XML used for the MR widget

Retention: 14 days. Override via `artifacts: { expire_in: ... }` on
the job.

## Self-hosted runners

The image is ~3.3 GB (Playwright base + browsers). For shared runners
that pull every job, cache the image at the runner level via your
runner's executor config — e.g. for Docker executor:

```toml
[runners.docker]
  image = "edgelensai/edgelens-sdk:0.1.1"
  pull_policy = "if-not-present"
```

That avoids the per-job pull and shaves 30-60s off cold starts.

## Examples

See [`examples/`](examples) for end-to-end snippets:
- [`pytest.gitlab-ci.yml`](examples/pytest.gitlab-ci.yml)
- [`playwright.gitlab-ci.yml`](examples/playwright.gitlab-ci.yml)
- [`matrix.gitlab-ci.yml`](examples/matrix.gitlab-ci.yml)
- [`self-hosted.gitlab-ci.yml`](examples/self-hosted.gitlab-ci.yml)

Depends on the CI image in [`ci/docker/`](../docker).
