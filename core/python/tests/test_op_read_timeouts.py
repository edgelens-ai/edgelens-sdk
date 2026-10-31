"""Long-running operations size their HTTP read timeout to the operation.

exec and inference results hold the request open for the requested time,
so the client must wait at least that long plus a margin. Every other
request keeps the client's configured timeout.
"""

from __future__ import annotations

import asyncio

from edgelens import EdgeLensClient
from edgelens.aio import AsyncEdgeLensClient

BASE = "https://api.edgelens.ai"

_SESSION = {
    "id": "sess_t",
    "status": "ready",
    "device": {
        "mac": "aa:bb:cc:00:00:01",
        "host": "10.0.1.42",
        "ssh_user": "recamera",
        "ssh_password": "secret",
        "os": "stock-os",
    },
}

_STATS = {"avg": 1.0, "min": 1.0, "max": 1.0, "p50": 1.0, "p95": 1.0, "p99": 1.0}

_EXEC = {"stdout": "", "stderr": "", "exit_code": 0}


def _add_session(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=f"{BASE}/v1/sessions/sess_t", json=_SESSION
    )


def _request_for(httpx_mock, suffix):
    return next(r for r in httpx_mock.get_requests() if str(r.url).endswith(suffix))


def test_sync_exec_read_timeout_covers_command(httpx_mock):
    _add_session(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/v1/sessions/sess_t/exec", json=_EXEC
    )
    client = EdgeLensClient(api_key="k")
    client.get_session("sess_t").device.exec("sleep 110", timeout=120)

    timeout = _request_for(httpx_mock, "/exec").extensions["timeout"]
    assert timeout["read"] >= 150


def test_sync_inference_run_read_timeout_covers_duration(httpx_mock):
    _add_session(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE}/v1/sessions/sess_t/inference/results",
        json={
            "duration_s": 120.0,
            "total_frames": 1,
            "fps": _STATS,
            "latency_ms": _STATS,
        },
    )
    client = EdgeLensClient(api_key="k")
    client.get_session("sess_t").device.inference.run(duration=120)

    timeout = _request_for(httpx_mock, "/inference/results").extensions["timeout"]
    assert timeout["read"] >= 150


def test_async_exec_read_timeout_covers_command(httpx_mock):
    _add_session(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/v1/sessions/sess_t/exec", json=_EXEC
    )

    async def run():
        async with AsyncEdgeLensClient(api_key="k") as client:
            sess = await client.get_session("sess_t")
            await sess.device.exec("sleep 110", timeout=120)

    asyncio.run(run())

    timeout = _request_for(httpx_mock, "/exec").extensions["timeout"]
    assert timeout["read"] >= 150


def test_other_requests_and_phases_keep_client_timeout(httpx_mock):
    _add_session(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/v1/sessions/sess_t/exec", json=_EXEC
    )
    client = EdgeLensClient(api_key="k")
    client.get_session("sess_t").device.exec("true", timeout=120)

    get_timeout = _request_for(httpx_mock, "/sessions/sess_t").extensions["timeout"]
    assert get_timeout["read"] == 30.0
    assert get_timeout["connect"] == 30.0

    exec_timeout = _request_for(httpx_mock, "/exec").extensions["timeout"]
    assert exec_timeout["connect"] == 30.0
    assert exec_timeout["write"] == 30.0
    assert exec_timeout["pool"] == 30.0


def test_larger_client_timeout_is_not_lowered(httpx_mock):
    _add_session(httpx_mock)
    httpx_mock.add_response(
        method="POST", url=f"{BASE}/v1/sessions/sess_t/exec", json=_EXEC
    )
    client = EdgeLensClient(api_key="k", timeout=900)
    client.get_session("sess_t").device.exec("true", timeout=60)

    timeout = _request_for(httpx_mock, "/exec").extensions["timeout"]
    assert timeout["read"] == 900
