# EdgeLens — GitHub Copilot instructions
#
# Drop this file at `.github/copilot-instructions.md` in the consumer
# project. Copilot loads it as repo-wide context for every completion.

This project tests against the **EdgeLens Edge AI Device Farm** —
a service that hands out real edge-AI cameras (Seeed reCamera,
RISC-V + Sophgo NPU) over the network. EdgeLens is framework-native:
use the test runner the project already uses (pytest, Playwright,
k6, Robot Framework). Do not invent an EdgeLens-specific runner.

## SDK shape

```python
from edgelens import EdgeLensClient

client = EdgeLensClient()  # reads $EDGELENS_API_KEY

with client.create_session(device_type="recamera-2002", os="stock-os") as session:
    session.wait_ready()
    device = session.device
    device.deploy(model="./face.cvimodel")
    stats = device.inference.run(duration=30)
    assert stats.fps.avg >= 15
    assert stats.latency_ms.p95 < 100
```

Async (`from edgelens.aio import AsyncEdgeLensClient`) mirrors the
sync surface and is the right choice in pytest-asyncio tests or
Node-driven runners.

In pytest projects, prefer the `device` fixture from
`edgelens-pytest` over hand-rolling `EdgeLensClient`. It handles
allocate + wait_ready + release.

```python
def test_face_latency(device):
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=30)
    assert stats.fps.avg >= 15
```

## OS tiers

- `"stock-os"` — reCamera firmware: `device.inference.*`, `device.display.*`, web UI, camera stream.
- `"recamagined"` — SSH-only raw OS; ship your own binary via `device.deploy(model=..., files=[...])` + `device.exec()`. Deployed files land in `/userdata/Models/` and aren't executable; `chmod +x` first.

The Python enum `OSType.STOCK` has value `"stock-os"`. Never suggest
the string `"stock"` (defunct legacy spelling).

## Generate

- `with client.create_session(...) as session:` for every test — release on exit.
- `session.wait_ready()` before touching `session.device`.
- One assertion per acceptance criterion.
- Catch only `edgelens.errors.{EdgeLensError, SessionError, AuthenticationError, DeviceError, TimeoutError}`.
- To use a different API base URL, pass `base_url=` to the client.

## Do not generate

- `os="stock"` — use `"stock-os"`.
- `time.sleep(N)` to wait for ready — use `session.wait_ready()`.
- Hard-coded device hosts (`10.0.1.42`) — always `session.device`.
- Manual `session.release()` inside a `with` block — the CM handles it.
- Mocks of `EdgeLensClient` or `Device` in tests that are supposed
  to run on real hardware. Mock at the model boundary instead.
- `try/except: pass` around EdgeLens errors — surface them.

## Frequent failure modes — what they actually mean

| Symptom | Meaning |
|---|---|
| `AuthenticationError` | `$EDGELENS_API_KEY` unset, malformed, or revoked. |
| `SessionError` on `wait_ready` | Flash failed; `session.error` carries the reason. |
| `TimeoutError` on `wait_ready` | Flash > 300s default; bump via `wait_ready(timeout=600)`. |
| HTTP 429 on create_session | `max_concurrent_sessions` full. |
| HTTP 410 on `device.*` | Session already released; start fresh. |
| HTTP 400 with `private` in detail | URL DNS-resolves to a private IP (SSRF block). |
| HTTP 422 with `extra fields not permitted` | Unknown key in request body. |
