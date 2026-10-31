# GitLab CI

The EdgeLens monorepo ships `.gitlab-ci.yml` templates under
[`ci/gitlab/`](../../ci/gitlab/) — include them with one line.

## Quickstart — pytest

```yaml
# .gitlab-ci.yml
include:
  - remote: https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/v0.2.4/ci/gitlab/edgelens.gitlab-ci.yml

hardware_tests:
  extends: .edgelens:pytest
  script:
    - pytest tests/hardware/ --junit-xml=$JUNIT_FILE --edgelens-os=stock-os
```

Set `EDGELENS_API_KEY` as a masked + protected CI/CD variable in
**Settings → CI/CD → Variables**.

Include the template from a release tag, as above, never from a branch:
GitLab fetches a remote include again for every pipeline, so a branch ref
runs whatever that branch holds at the time, with your API key in the job.
The tag also fixes the default image (`edgelensai/edgelens-sdk:0.2.4`).

## Templates available

All templates live in one file,
[`ci/gitlab/edgelens.gitlab-ci.yml`](../../ci/gitlab/edgelens.gitlab-ci.yml):

| Hidden job | What |
|---|---|
| `.edgelens:base` | Image, API-key check, JUnit report and artifact upload. Supply your own `script:`. |
| `.edgelens:pytest` | Runs `pytest --junit-xml=$JUNIT_FILE`. |
| `.edgelens:playwright` | Runs `npx playwright test` with the JUnit reporter. |
| `.edgelens:robot` | Runs `robot --output $JUNIT_FILE tests/`. |

Your real job `extends:` one of these. The hidden job carries the
image, the API-key check and the artifact wiring, so your job only
overrides `script:` or `variables:` where it needs to. There is no k6
template; build on `.edgelens:base` and run `k6` in your own `script:`.

## Variables

The templates accept these:

| Variable | Default | Purpose |
|---|---|---|
| `EDGELENS_API_KEY` | — | **Required.** Bearer token. Mask + protect it. |
| `EDGELENS_BASE_URL` | (default) | Override the API base URL. Honored directly by the SDK. |
| `EDGELENS_IMAGE` | `edgelensai/edgelens-sdk:0.2.4` | CI image. Defaults to the image released with the template, never `:latest`. |
| `JUNIT_FILE` | `junit.xml` (pytest) / `results.xml` (Playwright) / `output.xml` (Robot) | Path to the JUnit XML report. |

Device type and OS are test-runner options, not template variables:
pass them in your job's `script:` (for pytest, `--edgelens-os` and the
other flags in [the pytest guide](../frameworks/pytest.md)).

`wait_ready` no longer takes a client-side timeout knob: the platform
signals the readiness deadline on the session response and the SDK
trusts it, up to a client-side maximum of 30 minutes. Sessions that
never become ready are flipped to `ERROR` server-side; there is no
`EDGELENS_WAIT_TIMEOUT` to tune.

## Matrix-style fanout

GitLab calls it "parallel matrix":

```yaml
hardware_tests:
  extends: .edgelens:pytest
  parallel:
    matrix:
      - EDGELENS_OS: [stock-os, recamagined]
  script:
    - pytest tests/hardware/ --junit-xml=$JUNIT_FILE --edgelens-os=$EDGELENS_OS
```

Just like with GitHub Actions, GitLab fans out from its side but
EdgeLens enforces `max_concurrent_sessions` per key. Portal-minted keys
allow one concurrent session, and the portal has no control to change
that yet; size the fanout to the key's cap.

## Without the template (direct invocation)

```yaml
hardware_tests:
  image: python:3.12-slim
  script:
    - pip install edgelens-pytest
    - pytest tests/hardware/ --edgelens-os=stock-os
```

Define `EDGELENS_API_KEY` as a masked CI/CD variable; the plugin reads it
from the environment. Do not pass it with `--edgelens-key`, which puts
the value in the process list.

Same caveats as the [GitHub Actions](./github-actions.md) "without the
action" section.

## Failure triage

See the [GitHub Actions](./github-actions.md#failure-triage) section —
the symptom → cause mapping is identical.
