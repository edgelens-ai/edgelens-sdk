"""Basic tests for the EdgeLens client.

These tests use httpx mock transport — no real API calls.
"""

from __future__ import annotations

import pytest

from edgelens import (
    AuthenticationError,
    DeviceError,
    EdgeLensClient,
    OSType,
    SessionStatus,
)
from edgelens._http import HTTPClient
from edgelens.session import Session


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("EDGELENS_API_KEY", raising=False)
    with pytest.raises(AuthenticationError):
        EdgeLensClient()


def test_client_reads_env_var(monkeypatch):
    """api_key is not kept as a public
    attribute. The Authorization header on the underlying httpx
    client is the only persistent reference."""
    monkeypatch.setenv("EDGELENS_API_KEY", "test_key")
    client = EdgeLensClient()
    assert client._http._client.headers["Authorization"] == "Bearer test_key"


def test_base_url_reads_env_var(monkeypatch):
    """EDGELENS_BASE_URL was documented but silently ignored —
    every self-hosted user's requests went to the DEFAULT_BASE_URL
    (NXDOMAIN api.edgelens.ai). Env fallback must be honored."""
    monkeypatch.setenv("EDGELENS_API_KEY", "test_key")
    monkeypatch.setenv("EDGELENS_BASE_URL", "https://self-hosted.example.com")
    client = EdgeLensClient()
    assert str(client._http._client.base_url).rstrip("/") == "https://self-hosted.example.com"


def test_base_url_explicit_arg_wins_over_env(monkeypatch):
    """precedence: explicit arg > env > default."""
    monkeypatch.setenv("EDGELENS_API_KEY", "test_key")
    monkeypatch.setenv("EDGELENS_BASE_URL", "https://env-value.example.com")
    client = EdgeLensClient(base_url="https://arg-wins.example.com")
    assert str(client._http._client.base_url).rstrip("/") == "https://arg-wins.example.com"


def test_base_url_falls_back_to_default_when_no_env(monkeypatch):
    """precedence: default when nothing is set."""
    monkeypatch.setenv("EDGELENS_API_KEY", "test_key")
    monkeypatch.delenv("EDGELENS_BASE_URL", raising=False)
    from edgelens._http import DEFAULT_BASE_URL
    client = EdgeLensClient()
    assert str(client._http._client.base_url).rstrip("/") == DEFAULT_BASE_URL.rstrip("/")


def test_async_client_base_url_reads_env_var(monkeypatch):
    """async client mirrors the sync env-fallback."""
    from edgelens.aio import AsyncEdgeLensClient
    monkeypatch.setenv("EDGELENS_API_KEY", "test_key")
    monkeypatch.setenv("EDGELENS_BASE_URL", "https://self-hosted.example.com")
    client = AsyncEdgeLensClient()
    assert str(client._http._client.base_url).rstrip("/") == "https://self-hosted.example.com"


def test_session_pending_no_device(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_abc",
            "status": "pending",
        },
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()

    assert session.id == "sess_abc"
    assert session.status == SessionStatus.PENDING
    with pytest.raises(Exception):
        _ = session.device


def test_session_ready_with_device(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_xyz",
            "status": "ready",
            "expires_at": "2026-04-26T15:00:00Z",
            "device": {
                "mac": "2c:f7:f1:21:82:cf",
                "host": "10.0.1.42",
                "ssh_port": 22,
                "ssh_user": "recamera",
                "ssh_password": "secret",
                "web_ui": "http://10.0.1.42:9090",
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()

    assert session.status == SessionStatus.READY
    assert session.device.host == "10.0.1.42"
    assert session.device.os == OSType.STOCK
    assert session.device.web_ui == "http://10.0.1.42:9090"

    creds = session.device.ssh()
    assert creds.user == "recamera"
    assert creds.password == "secret"


def test_inference_unavailable_on_recamagined(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={
            "id": "sess_thin",
            "status": "ready",
            "device": {
                "mac": "2c:f7:f1:21:82:cf",
                "host": "10.0.1.42",
                "ssh_user": "recamera",
                "ssh_password": "secret",
                "os": "recamagined",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session(os="recamagined")

    with pytest.raises(DeviceError):
        session.device.inference.start()


def test_create_session_omits_image_version_when_unset(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_v", "status": "pending"},
    )

    client = EdgeLensClient(api_key="test_key")
    client.create_session()

    req = httpx_mock.get_requests()[0]
    import json as _json
    body = _json.loads(req.content)
    assert "image_version" not in body


def test_create_session_sends_image_version_when_set(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_v", "status": "pending"},
    )

    client = EdgeLensClient(api_key="test_key")
    client.create_session(image_version="0.2.3")

    req = httpx_mock.get_requests()[0]
    import json as _json
    body = _json.loads(req.content)
    assert body["image_version"] == "0.2.3"


def test_wait_ready_default_timeout_is_server_driven():
    """The customer-facing
    default is None — the SDK trusts the server-signaled `deadline`
    instead of a hardcoded client-side constant. Explicit `timeout=`
    remains as a caller-supplied ceiling for testing / abort-early."""
    import inspect

    from edgelens.aio import AsyncSession

    sync_default = inspect.signature(Session.wait_ready).parameters["timeout"].default
    async_default = inspect.signature(AsyncSession.wait_ready).parameters["timeout"].default
    assert sync_default is None
    assert async_default is None


def test_authentication_error_on_401(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        status_code=401,
        json={"message": "Invalid API key"},
    )

    client = EdgeLensClient(api_key="bad_key")
    with pytest.raises(AuthenticationError):
        client.create_session()
