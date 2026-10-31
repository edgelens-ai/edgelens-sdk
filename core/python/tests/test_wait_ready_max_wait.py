"""wait_ready has a client-side maximum wait.

With no caller ``timeout``, a server deadline is trusted only up to
``session.DEFAULT_MAX_WAIT_S`` (read through ``session._SAFETY_NET_S``, which
the tests shrink). A server that answers "pending" with a far-future
deadline, or pushes the deadline forward on every poll, must not hold
wait_ready forever, sync or async.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from edgelens import EdgeLensClient
from edgelens import session as session_mod
from edgelens.aio import AsyncEdgeLensClient
from edgelens.errors import TimeoutError as ELTimeoutError


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _extending_server(httpx_mock, session_id: str, *, far: bool) -> None:
    """POST and every GET answer 'pending'. ``far``: a deadline in the year
    9000; otherwise one that moves a minute later on every response."""
    state = {"deadline": datetime.now(timezone.utc) + timedelta(minutes=5)}

    def reply(request: httpx.Request) -> httpx.Response:
        if far:
            deadline = "9000-01-01T00:00:00Z"
        else:
            state["deadline"] += timedelta(minutes=1)
            deadline = _iso(state["deadline"])
        return httpx.Response(
            200, json={"id": session_id, "status": "pending", "deadline": deadline}
        )

    httpx_mock.add_callback(
        reply, method="POST", url="https://api.edgelens.ai/v1/sessions",
    )
    httpx_mock.add_callback(
        reply,
        method="GET",
        url=f"https://api.edgelens.ai/v1/sessions/{session_id}",
        is_reusable=True,
    )


def test_default_max_wait_is_thirty_minutes():
    assert session_mod.DEFAULT_MAX_WAIT_S == 30 * 60
    assert session_mod._SAFETY_NET_S == session_mod.DEFAULT_MAX_WAIT_S


@pytest.mark.parametrize("far", [True, False], ids=["far-future", "extending"])
def test_sync_wait_ready_stops_at_max_wait(httpx_mock, monkeypatch, far):
    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.1)
    _extending_server(httpx_mock, "sess_ext", far=far)

    sess = EdgeLensClient(api_key="test_key").create_session()
    with pytest.raises(ELTimeoutError, match="client-side maximum wait") as info:
        sess.wait_ready(poll_interval=0.01)
    assert "server deadline" in str(info.value)
    assert "timeout=" in str(info.value)


@pytest.mark.parametrize("far", [True, False], ids=["far-future", "extending"])
def test_async_wait_ready_stops_at_max_wait(httpx_mock, monkeypatch, far):
    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.1)
    _extending_server(httpx_mock, "sess_ext_a", far=far)

    async def run() -> None:
        client = AsyncEdgeLensClient(api_key="test_key")
        session = await client.create_session()
        await session.wait_ready(poll_interval=0.01)

    with pytest.raises(ELTimeoutError, match="client-side maximum wait"):
        asyncio.run(run())


def test_explicit_timeout_is_not_capped_by_max_wait(httpx_mock, monkeypatch):
    """The maximum applies only when no timeout is given; a caller who asks
    for longer gets their own ceiling."""
    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.01)
    _extending_server(httpx_mock, "sess_explicit", far=True)

    sess = EdgeLensClient(api_key="test_key").create_session()
    with pytest.raises(ELTimeoutError, match="caller-specified timeout=0.15"):
        sess.wait_ready(timeout=0.15, poll_interval=0.01)


def test_wait_ready_survives_unaddable_deadline(httpx_mock, monkeypatch):
    """A deadline at the very end of year 9999 cannot have the grace added
    to it without OverflowError; wait_ready must still reach its own limit
    instead of crashing."""
    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.05)
    edge = "9999-12-31T23:59:59Z"
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_edge", "status": "pending", "deadline": edge},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_edge",
        json={"id": "sess_edge", "status": "pending", "deadline": edge},
        is_reusable=True,
    )
    sess = EdgeLensClient(api_key="test_key").create_session()
    with pytest.raises(ELTimeoutError, match="client-side maximum wait"):
        sess.wait_ready(poll_interval=0.01)
