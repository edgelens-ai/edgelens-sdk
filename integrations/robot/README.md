# edgelens-robot

Robot Framework library for the EdgeLens Edge AI Device Farm. Keyword-
driven wrapper around the Python SDK — write `Request Device`,
`Deploy Model`, `Run Inference`, and let Robot drive the camera.

Counterpart to [`edgelens-pytest`](../pytest) for pytest users and
[`@edgelens/playwright-plugin`](../playwright) for JS/TS.

## Install

```sh
pip install edgelens-robot
```

Requires Python 3.9+ and Robot Framework 6.0+.

## Quickstart

```robotframework
*** Settings ***
Library             EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}
Suite Teardown      Release Device

*** Test Cases ***
Camera Renders The Test Pattern
    Request Device    os=stock-os
    Deploy Model    ./face.cvimodel
    Start Inference
    ${stats}=    Run Inference    duration=30
    Should Be True    ${stats}[fps][avg] > 15
```

Run it:

```sh
EDGELENS_API_KEY=el_test_xxx robot tests/
```

## Keywords

### Session lifecycle

| Keyword | Arguments | Returns |
|---|---|---|
| `Request Device` | `device_type=recamera-2002`, `os=stock-os`, `timeout=3600`, `wait_timeout=300` | Session id |
| `Release Device` | — | (no-op if no session) |
| `Get Session Id` | — | Session id |
| `Get Session Status` | — | Refreshes + returns status string |

### Device operations

| Keyword | Arguments | Returns |
|---|---|---|
| `Execute On Device` | `command`, `timeout=60.0` | `{stdout, stderr, exit_code}` dict |
| `Deploy Model` | `model`, `config=None`, `files=None` | dict |
| `Get SSH Details` | — | `{user, host, port}` dict |
| `Set SSH Password Variable` | `name=${SSH_PASSWORD}`, `scope=TEST` | Sets the variable without logging the value |
| `Get SSH Password` | — | Password string; Robot logs the assigned value at INFO, so prefer `Set SSH Password Variable` |
| `Get Device Info` | — | full info report dict |
| `Get Stream URL` | — | URL string (stock OS only) |

### Display

| Keyword | Arguments |
|---|---|
| `Play On Display` | `source`, `loop=False` |
| `Show On Display` | `source` |
| `Stop Display` | — |
| `Get Display Status` | — → `{ready, state, source}` |

### Inference (stock OS only)

| Keyword | Arguments |
|---|---|
| `Start Inference` | — |
| `Stop Inference` | — |
| `Run Inference Once` | — → detection dict |
| `Get Inference Stats` | — → snapshot dict |
| `Run Inference` | `duration=30.0`, `collect_frames=False` → full stats dict |

## Library scope

Default is **SUITE** — one camera per suite, shared across every test in
the file. The right tradeoff for read-only suites where allocation
takes 30s+. Override on the `Library` line:

```robotframework
Library    EdgeLensLibrary    scope=TEST     # fresh camera per test
Library    EdgeLensLibrary    scope=GLOBAL   # one camera across the whole run
```

## Configuration

| Argument | Default | Purpose |
|---|---|---|
| `api_key` | `%{EDGELENS_API_KEY}` | API key. Pass via env or library import. |
| `base_url` | — | Self-hosted EdgeLens deployments. |
| `scope` | `SUITE` | `SUITE` / `TEST` / `GLOBAL`. |

## CI

The `edgelensai/edgelens-sdk` image ships Robot Framework — drop the library
in and you're set:

### GitHub Actions

```yaml
- uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.1
  with:
    api-key: ${{ secrets.EDGELENS_API_KEY }}
    command: robot --output output.xml tests/
    junit-file: output.xml
```

### GitLab CI

```yaml
include:
  - remote: "https://raw.githubusercontent.com/edgelens-ai/edgelens-sdk/main/ci/gitlab/edgelens.gitlab-ci.yml"

edgelens-robot:
  extends: .edgelens:robot
```

## Develop

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## See also

Pairs with edgelens-pytest and @edgelens/playwright-plugin.
