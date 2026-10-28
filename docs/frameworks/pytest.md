# pytest

`pytest-edgelens` is auto-loaded by pytest via the `pytest11` entry
point. No `conftest.py` glue needed.

```bash
pip install pytest-edgelens
export EDGELENS_API_KEY=el_live_xxx
pytest
```

## Fixtures

| Fixture | Scope | What |
|---|---|---|
| `device` | session/module/function (CLI) | `edgelens.Device` past `wait_ready()` |
| `edgelens_session` | same as `device` | `edgelens.Session` |
| `edgelens_client` | session | `edgelens.EdgeLensClient` |
| `edgelens_options` | session | `EdgelensOptions` derived from CLI + env |

The default scope is `session` — one device for the whole pytest run.
The first test pays the flash cost; subsequent tests reuse it.

## CLI options

| Flag | Default | Purpose |
|---|---|---|
| `--edgelens-key` | — | API key. Prefer `$EDGELENS_API_KEY`: a value on the command line is visible in the process list and shell history. |
| `--edgelens-base-url` | — | Self-hosted EdgeLens deployments. |
| `--edgelens-os` | `stock-os` | OS to flash. Alt: `recamagined`. |
| `--edgelens-device-type` | `recamera-2002` | Device type to allocate. |
| `--edgelens-scope` | `session` | `session` / `module` / `function`. |
| `--edgelens-session-timeout` | `3600` | Session duration cap (s). |
| `--edgelens-skip-allocation` | off | Fixtures yield `None`. For plugin self-testing. |

`wait_ready` needs no client-side timeout knob: the platform commits
to a readiness deadline on the session response and the SDK trusts
it. Stuck sessions surface with the platform's own error reason on
the next poll after the deadline + grace, not with a generic
`TimeoutError`. `--edgelens-wait-timeout` still exists as a deprecated
escape hatch for testing / abort-early, but you shouldn't need it in
normal CI.

## OS marker

Pin a test to a specific OS so it's skipped when the active OS doesn't
match. Run pytest once per OS for full coverage.

```python
import pytest

@pytest.mark.edgelens(os="recamagined")
def test_recamagined_only(device):
    device.deploy(model="./models/m.cvimodel", files=["./build/my_binary"])
    r = device.exec("chmod +x /userdata/Models/my_binary && /userdata/Models/my_binary --check")
    assert r.success

@pytest.mark.edgelens(os="stock-os")
def test_stock_only(device):
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=10)
    assert stats.fps.avg >= 15

def test_either(device):
    """No marker → runs against whichever --edgelens-os is active."""
    info = device.info()
    assert info.hostname.startswith("reCamera")
```

Run once per OS:

```bash
pytest --edgelens-os=stock-os
pytest --edgelens-os=recamagined
```

## Picking a scope

- **session** (default) — read-only tests, or tests that leave the
  device in the same state they found it.
- **module** — one test file pollutes device state in a way the next
  file shouldn't see (`/tmp` writes, runtime config changes).
- **function** — every test must start from a clean flash. ~30 s
  overhead per test.

```bash
pytest --edgelens-scope=module
```

## Patterns

### Acceptance test against latency budget

```python
def test_face_p95_under_budget(device):
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=30)
    assert stats.latency_ms.p95 < 100, (
        f"p95 latency {stats.latency_ms.p95}ms exceeds 100ms budget"
    )
```

### Parametrize across models

```python
import pytest

MODELS = [
    ("face", "./models/face.cvimodel", 15),
    ("person", "./models/person.cvimodel", 12),
    ("vehicle", "./models/vehicle.cvimodel", 10),
]

@pytest.mark.parametrize("name,path,min_fps", MODELS, ids=lambda x: x if isinstance(x, str) else None)
def test_model_meets_fps_floor(device, name, path, min_fps):
    device.deploy(model=path)
    stats = device.inference.run(duration=20)
    assert stats.fps.avg >= min_fps, f"{name}: {stats.fps.avg} < {min_fps}"
```

Tip: use `--edgelens-scope=module` here so all three parametrize
variants share one device.

### Running your own binary on `recamagined`

```python
@pytest.mark.edgelens(os="recamagined")
def test_custom_binary_runs_clean(device):
    device.deploy(model="./models/m.cvimodel", files=["./build/my_inference"])
    r = device.exec(
        "chmod +x /userdata/Models/my_inference && "
        "/userdata/Models/my_inference --model /userdata/Models/m.cvimodel --duration 5"
    )
    assert r.success, r.stderr
    assert "ERROR" not in r.stdout
```

On reCamaginedOS, `deploy(model=..., files=[...])` places the model and
each file in `/userdata/Models/` under its base filename. Files arrive
readable but not executable: make a deployed binary executable
(`chmod +x`) before running it.

## Anti-patterns

- `time.sleep(N)` to wait for ready — the fixture has already done it.
  If you're sleeping in a test, something's wrong.
- Mocking `EdgeLensClient` in a test that's *supposed* to hit hardware.
  Use `--edgelens-skip-allocation` only for plugin-self-testing.
- Manual `session.release()` inside a fixture-scoped test — the
  fixture's teardown handles it.
- Catching bare `Exception` to "make the test pass" — let real bugs
  propagate.

## Example project

Full working project: [`examples/pytest/`](../../examples/pytest/).
Clone the repo, set `EDGELENS_API_KEY`, and `pytest` runs.
