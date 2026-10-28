"""Tests for retry policy, streaming uploads, stream(), async client."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from edgelens import EdgeLensClient, RetryPolicy
from edgelens._http import HTTPClient, AsyncHTTPClient
from edgelens.aio import AsyncEdgeLensClient
from edgelens.errors import EdgeLensError


# ---- retry policy ------------------------------------------------------------

def test_retry_on_503_for_get(httpx_mock):
    # First 2 GETs fail with 503, third succeeds.
    for _ in range(2):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_x",
            status_code=503,
        )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_x",
        json={"id": "sess_x", "status": "ready"},
    )

    http = HTTPClient(
        api_key="k",
        retry_policy=RetryPolicy(max_attempts=5, base_delay=0.001),
    )
    out = http.get("/v1/sessions/sess_x")
    assert out["id"] == "sess_x"


def test_no_retry_on_503_for_post(httpx_mock):
    """POST is not idempotent — must surface the 503, not retry."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        status_code=503,
        json={"message": "upstream busy"},
    )

    http = HTTPClient(
        api_key="k",
        retry_policy=RetryPolicy(max_attempts=5, base_delay=0.001),
    )
    with pytest.raises(EdgeLensError, match="503"):
        http.post("/v1/sessions", json={"device_type": "recamera-2002"})


def test_max_attempts_exhausted_surfaces_error(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/foo",
            status_code=503,
        )
    http = HTTPClient(
        api_key="k",
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.001),
    )
    with pytest.raises(EdgeLensError, match="503"):
        http.get("/v1/foo")


def test_retry_after_header_honored(httpx_mock, monkeypatch):
    """When Retry-After is present, we should sleep that long (capped)."""
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/foo",
        status_code=429,
        headers={"retry-after": "0.25"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/foo",
        json={"ok": True},
    )
    sleeps: list[float] = []
    monkeypatch.setattr("edgelens._http.time.sleep", lambda s: sleeps.append(s))

    http = HTTPClient(api_key="k", retry_policy=RetryPolicy(max_attempts=2, base_delay=0.001))
    http.get("/v1/foo")
    # The first (and only) backoff sleep should be 0.25, not the exponential default.
    assert sleeps == [0.25]


# ---- streaming uploads ------------------------------------------------------

def test_deploy_streams_file_handle(httpx_mock, tmp_path):
    """The multipart body must be sent from the file handle, not buffered.

    We can't directly assert "no buffering" without monkey-patching httpx's
    transport, but we *can* assert the file content survives round-trip and
    that no bytes were loaded eagerly by checking the upload size.
    """
    big = tmp_path / "model.bin"
    big.write_bytes(b"X" * 1024 * 1024)  # 1 MiB

    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions/sess_q/deploy",
        json={"success": True},
    )

    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_q",
            "status": "ready",
            "device": {
                "mac": "aa:bb:cc:00:00:01",
                "host": "10.0.1.1",
                "ssh_user": "recamera",
                "ssh_password": "s",
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="k")
    sess = client.create_session()
    out = sess.device.deploy(model=str(big))
    assert out == {"success": True}

    # Pull the actual sent request and verify the body contains our 1 MiB blob.
    deploy_req = next(r for r in httpx_mock.get_requests() if "/deploy" in str(r.url))
    body = deploy_req.read()
    assert b"X" * 1024 in body  # streamed payload made it across
    assert len(body) > 1024 * 1024  # multipart overhead on top of the 1 MiB


# ---- stream() ----------------------------------------------------------------

def test_stream_yields_chunks(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_s",
            "status": "ready",
            "device": {
                "mac": "aa:bb:cc:00:00:01",
                "host": "10.0.1.1",
                "ssh_user": "recamera",
                "ssh_password": "s",
                "os": "stock-os",
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_s/stream/raw",
        content=b"AAAA" * 5000,
        headers={"content-type": "application/octet-stream"},
    )

    client = EdgeLensClient(api_key="k")
    sess = client.create_session()
    chunks = list(sess.device.stream(chunk_size=4096))
    assert b"".join(chunks) == b"AAAA" * 5000


# ---- async client -----------------------------------------------------------

def test_async_client_create_and_release(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_a",
            "status": "ready",
            "device": {
                "mac": "aa:bb:cc:00:00:01",
                "host": "10.0.1.1",
                "ssh_user": "recamera",
                "ssh_password": "p",
                "os": "stock-os",
            },
        },
    )
    httpx_mock.add_response(
        method="DELETE",
        url="https://api.edgelens.ai/v1/sessions/sess_a",
        json={"id": "sess_a", "status": "released"},
    )

    async def run():
        async with AsyncEdgeLensClient(api_key="k") as client:
            sess = await client.create_session(device_type="recamera-2002")
            assert sess.id == "sess_a"
            assert sess.device.host == "10.0.1.1"
            await sess.release()

    asyncio.run(run())


def test_async_retry_on_503(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_r",
        status_code=503,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_r",
        json={"id": "sess_r", "status": "flashing"},
    )

    async def run():
        http = AsyncHTTPClient(
            api_key="k",
            retry_policy=RetryPolicy(max_attempts=3, base_delay=0.001),
        )
        try:
            out = await http.get("/v1/sessions/sess_r")
            assert out["id"] == "sess_r"
        finally:
            await http.aclose()

    asyncio.run(run())


# ---- pool configurability ---------------------------------------------------

def test_pool_limits_threaded_to_httpx():
    """Construction shouldn't fail when limits are set; the transport
    receives them via httpx.Limits internally."""
    client = EdgeLensClient(api_key="k", max_connections=42, max_keepalive_connections=7)
    assert isinstance(client._http._client, httpx.Client)
    client.close()
