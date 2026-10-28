# Getting Started

Run your first test against a real edge AI device in under five minutes.

## 1. Sign up + mint an API key

1. Sign up at [https://edgelens.ai](https://edgelens.ai).
2. In the portal, open **API Keys** → **Create key**.
3. Copy the key once — it is shown to you exactly once. Store it like a password.

The portal mints keys server-side, so the value in the form is the
authoritative one — there is nothing to paste, only to copy out.

## 2. Set the environment variable

```bash
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
```

Add it to your shell rc file if you'll be running tests often. The SDK
also reads from a `.env` file in the working directory if your project
already uses `python-dotenv`.

## 3. Pick a framework

EdgeLens is framework-native — the same SDK plugs into whatever runner
you already use:

```bash
# pytest
pip install pytest-edgelens

# Playwright (Node)
npm install --save-dev @edgelens/playwright-plugin

# Robot Framework
pip install robotframework-edgelens

# k6 (Go-based, builds a custom k6 binary)
xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6
```

Each framework guide ([pytest](./frameworks/pytest.md), [Playwright](./frameworks/playwright.md), [k6](./frameworks/k6.md), [Robot](./frameworks/robot.md)) walks you through the plugin's options.

## 4. Write your first test

Using pytest (the shortest path):

```python
# tests/test_first.py
def test_face_detection_meets_latency_target(device):
    """Real reCamera. Real model. Real measurement."""
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=10)
    assert stats.fps.avg >= 15
    assert stats.latency_ms.p95 < 100
```

The `device` fixture comes from `pytest-edgelens`. It allocates a real
device, flashes it, waits for `status=ready`, and releases on test exit
— you write the assertion, EdgeLens handles the rest.

Run it:

```bash
pytest tests/test_first.py
```

The first run flashes the OS, so it takes longer than later runs.
Subsequent runs in the same pytest session reuse the device.

## 5. What just happened

| Step | Where |
|---|---|
| Bearer token sent | `Authorization: Bearer $EDGELENS_API_KEY` to the platform API |
| Session allocated | `POST /v1/sessions` — the platform assigns an available camera and prepares it |
| Wait for ready | Polled `GET /v1/sessions/{id}` until `status=ready` |
| Model deployed | `POST /v1/sessions/{id}/deploy` — the platform deploys it to the camera |
| Inference run | `POST /v1/sessions/{id}/inference/results` with `duration=10` |
| Session released | `DELETE /v1/sessions/{id}` on test exit, even if the assertion failed |

See the [API reference](./api-reference.md) for the full request/response shape of each step.

## Pick your OS tier

EdgeLens offers two OS tiers per device. Pick the one that matches what
you actually need to test:

| OS | What you get | When to use |
|---|---|---|
| `"stock-os"` (default) | reCamera firmware — `device.inference.*`, `device.display.*`, web UI, camera stream | You want EdgeLens to run inference for you; you only care about metrics. |
| `"recamagined"` | SSH-only raw OS | You ship your own inference binary; you deploy + exec it yourself. |

Pin a test to a tier:

```python
import pytest

@pytest.mark.edgelens(os="recamagined")
def test_my_custom_binary(device):
    device.deploy(model="./models/m.cvimodel", files=["./build/my_inference"])
    r = device.exec(
        "chmod +x /userdata/Models/my_inference && "
        "/userdata/Models/my_inference --model /userdata/Models/m.cvimodel --duration 10"
    )
    assert r.success
```

On reCamaginedOS, `deploy(model=..., files=[...])` places the model and
each file in `/userdata/Models/` under its base filename. Files arrive
readable but not executable: make a deployed binary executable
(`chmod +x`) before running it.

## Next steps

- **[API reference](./api-reference.md)** — the underlying HTTP surface.
- **Framework guides** — [pytest](./frameworks/pytest.md), [Playwright](./frameworks/playwright.md), [k6](./frameworks/k6.md), [Robot](./frameworks/robot.md).
- **[CI/CD](./ci-cd/github-actions.md)** — run EdgeLens tests on every PR.
- **[Examples](../examples/)** — copy-pasteable working projects.
