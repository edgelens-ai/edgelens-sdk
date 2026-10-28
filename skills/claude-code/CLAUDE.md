# EdgeLens — Claude Code skill

You are writing tests against the **EdgeLens Edge AI Device Farm**.
EdgeLens hands out real edge-AI cameras (Seeed reCamera, RISC-V +
Sophgo NPU) over the network so tests run on real hardware. EdgeLens
is framework-native — customers use the test runner they already
know (pytest, Playwright, k6, Robot) and pull devices in via a
plugin. There is no EdgeLens-specific runner.

This skill ships with the `edgelens-sdk` Python SDK. For non-Python work
read the relevant integration's README (`integrations/<framework>/`)
before writing.

## Before you write

- Run `pip show edgelens-sdk` (or `npm ls @edgelens/core`) to confirm the
  SDK is installed. If it isn't, the test plan you're writing will
  not run — call this out before going further.
- Check whether the project has `pytest-edgelens`, `@edgelens/playwright-plugin`,
  `xk6-edgelens`, or `EdgeLensLibrary` (Robot) listed. The plugin is
  almost always preferable to driving the core client by hand — it
  handles allocation, wait_ready, and release.
- `$EDGELENS_API_KEY` must be set. Don't write tests that hard-code
  keys or paste them into examples.

## Canonical Python pattern

```python
from edgelens import EdgeLensClient

client = EdgeLensClient()  # reads $EDGELENS_API_KEY

with client.create_session(device_type="recamera-2002", os="stock-os") as session:
    session.wait_ready()
    device = session.device
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=30)
    assert stats.fps.avg >= 15
    assert stats.latency_ms.p95 < 100
```

Async (`from edgelens.aio import AsyncEdgeLensClient`) mirrors the
sync surface and is the right choice inside `pytest-asyncio` tests or
when called from Playwright/Node.

## Canonical pytest pattern

The `device` fixture is from `pytest-edgelens`. **Prefer it.**

```python
import pytest

def test_face_latency(device):
    device.deploy(model="./models/face.cvimodel")
    stats = device.inference.run(duration=30)
    assert stats.fps.avg >= 15
    assert stats.latency_ms.p95 < 100

@pytest.mark.edgelens(os="recamagined")
def test_my_inference_binary(device):
    device.deploy(model="./models/m.cvimodel", files=["./build/my_infer"])
    r = device.exec(
        "chmod +x /userdata/Models/my_infer && "
        "/userdata/Models/my_infer --model /userdata/Models/m.cvimodel --duration 10"
    )
    assert r.success, r.stderr
```

On reCamaginedOS, `deploy(model=..., files=[...])` places the model and
each file in `/userdata/Models/` under its base filename. Files arrive
readable but not executable: `chmod +x` a deployed binary before running it.

Invoke pytest with `$EDGELENS_API_KEY` set in the environment (never
pass the key on the command line) and `--edgelens-os=stock-os|recamagined`
if the marker isn't set. Scope defaults to `session` — set `--edgelens-scope=function`
only when each test mutates device state irrecoverably.

## OS tiers

| OS | What you get | When to use |
|---|---|---|
| `stock-os` | reCamera firmware: `device.inference.*`, `device.display.*`, web UI, stream | Metrics, screen-on demos, anything that uses the built-in inference engine |
| `recamagined` | SSH-only raw OS | You ship the inference binary; no built-in inference / display HTTP |

The SDK exposes `OSType.STOCK` and `OSType.RECAMAGINED`. **The string
value of `OSType.STOCK` is `"stock-os"`** — not `"stock"`. Always
pass `"stock-os"` to API surfaces.

## Decision rules

1. **Don't mock `EdgeLensClient` / `Device` in tests that are supposed
   to hit real hardware.** EdgeLens exists *because* mocks miss
   hardware-level failures. If the user wants a unit test, draw the
   line at the model boundary, not the SDK boundary.
2. **One assertion per acceptance criterion.** Don't bundle "fps OK,
   latency OK, no segfault, output JSON valid" behind one `assert`.
3. **Use `session.wait_ready()`** before touching `session.device`.
   Skipping it raises `SessionError`.
4. **Catch only `edgelens.errors.*`** — never bare `Exception`.
5. **Hardware tests are slow.** Don't loop them 100 times for
   "statistics" inside one test; use `inference.run(duration=N)` which
   collects N seconds of data efficiently.

## Anti-patterns — don't write these

- `os="stock"` — defunct. Use `"stock-os"`.
- `time.sleep(5)` to "wait for ready" — use `session.wait_ready()`,
  which has the right back-off and timeout.
- Hard-coded device hosts (`10.0.1.42`) — go through `session.device`.
- Manual `session.release()` inside a `with client.create_session(...)`
  block — the context manager does it.
- Catching `EdgeLensError` to "make the test pass" — surface the failure.

## When the user asks you to write a test

Match the test to what they asked for, not what's interesting:

1. Identify framework (pytest / Playwright / k6 / Robot) — ask if unclear.
2. Identify OS tier from the test description — ask if unclear.
3. Identify the actual acceptance criterion. "Make sure inference works"
   isn't a criterion; "fps ≥ 15 on the crowd_scene clip" is.
4. Write the *thinnest* test that checks the criterion. Resist the
   urge to deploy + display + inference all in one test unless that
   combination is what's being checked.
5. If you wrote a destructive test (file uploads to `/tmp`, system
   config edits), set `--edgelens-scope=function` or use a fresh
   session in-test so the next test isn't poisoned.

## When the user asks for help with a failure

| Symptom | What it actually means |
|---|---|
| `AuthenticationError` | `$EDGELENS_API_KEY` unset, malformed, or revoked. Check the portal. |
| `SessionError` on `wait_ready` | Device flash failed. `session.error` carries the platform's reason. |
| `TimeoutError` on `wait_ready` | Explicit `timeout=` ceiling fired, OR the safety-net (~30 min) fired because the api returned no server `deadline`. SDK trusts the platform's deadline in normal use. |
| HTTP 429 from `create_session` | `max_concurrent_sessions` is full. Release prior sessions or upgrade the plan. |
| HTTP 410 from `device.*` | Session already released. Stop using the stale `device`; start a fresh session. |
| HTTP 400 with `private` in detail | You passed a URL that DNS-resolves to a private IP. The platform blocks SSRF — use a public-internet URL. |
| HTTP 422 with `extra fields not permitted` | The request model has `extra="forbid"`. Drop the unknown key. |

Always surface the full error chain — don't `try/except: pass` to make output cleaner.

## Files in this skill

- `CLAUDE.md` — this file (Claude Code skill instructions).
- `../prompts/edgelens-system-prompt.md` — generic LLM prompt, same shape.
- `../cursor/.cursorrules` — Cursor IDE rules.
- `../copilot/.github/copilot-instructions.md` — GitHub Copilot.

The EdgeLens MCP server (`integrations/mcp/`) exposes the same surface
as a tool catalogue when the user wants the LLM to drive sessions
directly instead of just generating test code. Its tools act only on
sessions that server created unless the operator sets
`EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS=1`. Its `exec_command` tool is off
unless the operator sets `EDGELENS_MCP_EXEC_ENABLED=1`, and once enabled
it is an unrestricted shell on the device: no command is filtered.
