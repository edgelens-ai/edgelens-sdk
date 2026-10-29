# edgelens-pytest

pytest plugin for the EdgeLens Edge AI Device Farm — write a test that
gets a real edge AI camera as a fixture, with auto-allocate, auto-
release, configurable scope, OS filtering, and JUnit metadata.

Counterpart to [`@edgelens/playwright-plugin`](../playwright) for
the Python world.

## Install

```sh
pip install edgelens-pytest
```

Requires Python 3.9+. Auto-loaded by pytest via the `pytest11` entry
point — no `conftest.py` glue needed.

## Quickstart

```python
# tests/test_camera.py
def test_inference_latency(device):
    device.deploy(model="./face.cvimodel")
    device.inference.start()
    stats = device.inference.run(duration=30)
    assert stats.fps.avg > 15
    assert stats.latency_ms.p95 < 100
```

Run it:

```sh
export EDGELENS_API_KEY=el_test_xxx
pytest
```

`device` is **session-scoped** by default — one camera for the whole
run. Use `--edgelens-scope=module` or `--edgelens-scope=function` if
tests mutate device state in ways the next test would inherit broken.

## Fixtures

| Fixture | Scope | What |
|---|---|---|
| `device` | session/module/function (CLI) | `edgelens.Device` ready to use |
| `edgelens_session` | same as `device` | `edgelens.Session`, already past `wait_ready()` |
| `edgelens_client` | session | `edgelens.EdgeLensClient` |
| `edgelens_options` | session | `EdgelensOptions` derived from CLI + env |

## CLI options

| Flag | Default | Purpose |
|---|---|---|
| `--edgelens-key` | — | API key. Prefer `$EDGELENS_API_KEY`: a value on the command line is visible in the process list and shell history. |
| `--edgelens-base-url` | — | Self-hosted EdgeLens deployments. |
| `--edgelens-os` | `stock-os` | OS to flash. Alt: `recamagined`. |
| `--edgelens-device-type` | `recamera-2002` | Device type to allocate. |
| `--edgelens-scope` | `session` | `session` / `module` / `function`. |
| `--edgelens-session-timeout` | `3600` | Session duration cap (s). |
| `--edgelens-skip-allocation` | off | Fixtures yield `None`. For plugin-self-testing. |

`wait_ready` does not need a client-side timeout: the platform
signals a readiness deadline on the session response and the
SDK trusts it. `--edgelens-wait-timeout` is a deprecated
escape hatch; setting it emits a `PytestDeprecationWarning`.

## OS marker

Pin a test to a specific OS via `@pytest.mark.edgelens(os=...)`:

```python
import pytest

@pytest.mark.edgelens(os="recamagined")
def test_recamagined_only(device):
    ...

@pytest.mark.edgelens(os="stock-os")
def test_stock_only(device):
    ...

def test_works_on_either(device):
    ...
```

Run once per OS:

```sh
pytest --edgelens-os=stock-os
pytest --edgelens-os=recamagined
```

Marker mismatches surface as `pytest.mark.skip` with a clear reason, so
the report tells you why a test was excluded.

The same pattern works for `device_type`:

```python
@pytest.mark.edgelens(device_type="some-other-device")
def test_only_for_other(device):
    ...
```

## Multi-OS coverage

The fixture is session-scoped by default — one camera for the run.
Mixing OS variants under a single scope would require multiple sessions,
which we deliberately don't support implicitly (allocations cost money
+ wall-clock time).

To cover multiple OS variants in CI, run pytest once per OS:

```yaml
# .github/workflows/edgelens-matrix.yml
strategy:
  matrix:
    os: [stock, recamagined]
steps:
  - uses: actions/checkout@v4
  - uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.2
    with:
      api-key: ${{ secrets.EDGELENS_API_KEY }}
      command: pytest --edgelens-os=${{ matrix.os }} --junit-xml=junit.xml
```

For fine-grained per-test OS switching inside a single run, drop the
fixture scope to `function` and add a custom `os_variant` parametrize
in your own `conftest.py` (see the SDK example projects).

## JUnit metadata

Each test's testcase in the JUnit XML gets these extra `<property>`
entries:

- `edgelens_session_id`
- `edgelens_mac`
- `edgelens_host`
- `edgelens_os`

So the GitLab MR widget / GitHub Action summary / CI dashboard can show
*which camera ran which test* without parsing logs.

## Develop

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## See also

Pairs with `@edgelens/playwright-plugin` for JS/TS teams.
