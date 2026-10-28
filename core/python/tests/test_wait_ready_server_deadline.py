"""Session.wait_ready is server-driven via the server's `deadline` field.

The SDK polls status until READY/ERROR/EXPIRED or the server-returned
`deadline` is in the past. Explicit `timeout=` is a ceiling override
for testing / abort-early. The safety-net fires only when the server
returns no deadline at all (an older api version or broken response).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from edgelens import EdgeLensClient
from edgelens.aio import AsyncEdgeLensClient
from edgelens.errors import SessionError, TimeoutError as ELTimeoutError
from edgelens.session import _parse_deadline


# ---- _parse_deadline tz-coerce guard ---------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "2026-08-30T15:47:58",         # naive — bare (SQLite dev round-trip)
        "2026-08-30T15:47:58Z",        # tz-aware — Z-suffixed
        "2026-08-30T15:47:58+00:00",   # tz-aware — offset
        "2026-08-30T15:47:58.123456",  # naive with microseconds
    ],
)
def test_parse_deadline_always_returns_tz_aware(raw):
    """refresh's monotonicity guard compares deadlines across
    polls. A naive-vs-aware mismatch TypeErrors — coerce to UTC when
    the input lacks tzinfo so both sides are always comparable."""
    parsed = _parse_deadline(raw)
    assert parsed is not None
    assert parsed.tzinfo is not None, f"{raw!r} parsed to naive datetime"


def test_parse_deadline_none_for_empty_or_bad_input():
    for raw in (None, "", "not-a-date", "2026-13-40T99:99:99"):
        assert _parse_deadline(raw) is None


def test_parse_deadline_preserves_explicit_offset():
    """If the api ever emits a non-UTC offset (unlikely per contract,
    but possible), do NOT rewrite it to UTC — preserve what was sent
    so the wire-value round-trips."""
    parsed = _parse_deadline("2026-08-30T15:47:58+05:30")
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=5, minutes=30)


def test_refresh_survives_naive_and_aware_deadline_mix(httpx_mock):
    """POST returns a Z-suffixed (tz-aware) deadline and GET returns a
    bare (naive) one, as a backend that drops tzinfo on round-trip
    does. The monotonicity guard in refresh() must NOT TypeError under
    this mix: both sides are coerced to tz-aware by _parse_deadline."""
    deadline_dt = datetime.now(timezone.utc) + timedelta(minutes=15)
    z_suffixed = deadline_dt.isoformat().replace("+00:00", "Z")
    # Emulate SQLite's naive round-trip: same wall-clock, no tz suffix.
    naive_wire = deadline_dt.replace(tzinfo=None).isoformat()

    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_tzmix", "status": "flashing", "deadline": z_suffixed},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_tzmix",
        json={
            "id": "sess_tzmix",
            "status": "ready",
            "deadline": naive_wire,
            "device": {
                "mac": "aa:bb:cc:00:00:99",
                "host": "10.0.0.99",
                "ssh_user": "recamera",
                "ssh_password": "x" * 20,
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()
    # Comparing naive to aware would raise TypeError on the first refresh poll.
    ready = session.wait_ready(poll_interval=0.01)
    assert ready.status.value == "ready"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_wait_ready_returns_when_status_flips_to_ready(httpx_mock):
    """Happy path: server returns FLASHING then READY, both with a
    deadline in the future. wait_ready returns on the READY poll."""
    deadline = datetime.now(timezone.utc) + timedelta(minutes=15)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_ok", "status": "flashing", "deadline": _iso(deadline)},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_ok",
        json={
            "id": "sess_ok",
            "status": "ready",
            "deadline": _iso(deadline),
            "device": {
                "mac": "aa:bb:cc:00:00:01",
                "host": "10.0.0.5",
                "ssh_user": "recamera",
                "ssh_password": "x" * 20,
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()
    assert session.deadline is not None

    ready = session.wait_ready(poll_interval=0.01)
    assert ready.status.value == "ready"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_wait_ready_raises_session_error_when_platform_stuck_past_grace(
    httpx_mock, monkeypatch,
):
    """SDK waits ``_DEADLINE_GRACE_S`` past the server's deadline
    to give the platform time to flip to ERROR itself. Only when the
    platform IS stuck (still FLASHING well past deadline + grace) does
    the SDK raise, and its message points at a stuck platform."""
    from edgelens import session as session_mod
    monkeypatch.setattr(session_mod, "_DEADLINE_GRACE_S", 0.0)

    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_stuck", "status": "flashing", "deadline": _iso(past)},
    )
    for _ in range(10):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_stuck",
            json={"id": "sess_stuck", "status": "flashing", "deadline": _iso(past)},
        )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()

    with pytest.raises(SessionError, match="platform may be stuck"):
        session.wait_ready(poll_interval=0.01)


def test_wait_ready_grace_lets_platform_error_surface(httpx_mock):
    """within the grace period past the server deadline, the SDK
    keeps polling so the platform's own ERROR (with its actual reason
    from db.error_message) surfaces — instead of the SDK raising a
    speculative SessionError that loses the real cause."""
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_grace", "status": "flashing", "deadline": _iso(past)},
    )
    # First poll: still FLASHING (past deadline, but inside default
    # 30s grace) — SDK must NOT raise here.
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_grace",
        json={"id": "sess_grace", "status": "flashing", "deadline": _iso(past)},
    )
    # Platform catches up and reports ERROR — SDK surfaces
    # this with the platform's own status, not a speculation.
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_grace",
        json={"id": "sess_grace", "status": "error", "deadline": _iso(past)},
    )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()

    with pytest.raises(SessionError, match="ended in state error"):
        session.wait_ready(poll_interval=0.01)


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_wait_ready_explicit_timeout_wins_when_shorter(httpx_mock, monkeypatch):
    """Caller-supplied ceiling fires before the server deadline would.
    Message names the caller value so debugging isn't misleading."""
    far_future = datetime.now(timezone.utc) + timedelta(minutes=15)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_ceiling", "status": "flashing", "deadline": _iso(far_future)},
    )
    for _ in range(20):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_ceiling",
            json={"id": "sess_ceiling", "status": "flashing", "deadline": _iso(far_future)},
        )

    client = EdgeLensClient(api_key="test_key")
    session = client.create_session()

    with pytest.raises(ELTimeoutError, match="caller-specified timeout=0"):
        session.wait_ready(timeout=0.05, poll_interval=0.01)


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_wait_ready_safety_net_fires_when_no_deadline_field(httpx_mock, monkeypatch):
    """An older api version / broken response omits `deadline`. Safety net
    catches it eventually (monkey-patched to a tiny value so the test
    isn't slow) and the message says the api is out of date."""
    from edgelens import session as session_mod

    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.05)

    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_old_api", "status": "flashing"},
    )
    for _ in range(20):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_old_api",
            json={"id": "sess_old_api", "status": "flashing"},
        )

    client = EdgeLensClient(api_key="test_key")
    sess = client.create_session()
    assert sess.deadline is None

    with pytest.raises(ELTimeoutError, match="safety-net"):
        sess.wait_ready(poll_interval=0.01)


def test_deadline_monotonicity_ignores_backward_revision(httpx_mock):
    """server contract: deadline is monotonically non-decreasing across
    polls. If the server suddenly returns an earlier deadline (bug or
    malicious), keep the previously-observed one."""
    original = datetime.now(timezone.utc) + timedelta(minutes=15)
    earlier = original - timedelta(minutes=10)

    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_mono", "status": "flashing", "deadline": _iso(original)},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_mono",
        json={"id": "sess_mono", "status": "flashing", "deadline": _iso(earlier)},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_mono",
        json={
            "id": "sess_mono",
            "status": "ready",
            "deadline": _iso(earlier),
            "device": {
                "mac": "aa:bb:cc:00:00:02",
                "host": "10.0.0.6",
                "ssh_user": "recamera",
                "ssh_password": "x" * 20,
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    sess = client.create_session()
    stored_before = sess.deadline

    sess.wait_ready(poll_interval=0.01)
    assert sess.deadline == stored_before, (
        "SDK must not accept a backward deadline revision — the value "
        "should stay at the first-observed original."
    )


def test_async_wait_ready_returns_when_status_flips_to_ready(httpx_mock):
    """Async mirror: same server-driven happy path."""
    deadline = datetime.now(timezone.utc) + timedelta(minutes=15)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_ok_a", "status": "flashing", "deadline": _iso(deadline)},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_ok_a",
        json={
            "id": "sess_ok_a",
            "status": "ready",
            "deadline": _iso(deadline),
            "device": {
                "mac": "aa:bb:cc:00:00:0a",
                "host": "10.0.0.8",
                "ssh_user": "recamera",
                "ssh_password": "x" * 20,
                "os": "stock-os",
            },
        },
    )

    async def run() -> str:
        client = AsyncEdgeLensClient(api_key="test_key")
        session = await client.create_session()
        ready = await session.wait_ready(poll_interval=0.01)
        return ready.status.value

    assert asyncio.run(run()) == "ready"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_async_wait_ready_raises_when_platform_stuck_past_grace(
    httpx_mock, monkeypatch,
):
    """async mirror: stuck-platform check honors _DEADLINE_GRACE_S
    via attribute lookup on the session module — so a
    monkeypatch on the sync module reaches the async wait_ready too."""
    from edgelens import session as session_mod
    monkeypatch.setattr(session_mod, "_DEADLINE_GRACE_S", 0.0)

    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_stuck_a", "status": "flashing", "deadline": _iso(past)},
    )
    for _ in range(10):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_stuck_a",
            json={"id": "sess_stuck_a", "status": "flashing", "deadline": _iso(past)},
        )

    async def run() -> None:
        client = AsyncEdgeLensClient(api_key="test_key")
        session = await client.create_session()
        await session.wait_ready(poll_interval=0.01)

    with pytest.raises(SessionError, match="platform may be stuck"):
        asyncio.run(run())


def test_time_to_deadline_returns_delta_when_deadline_present(httpx_mock):
    """helper returns roughly (deadline - now) for progress-bar UIs."""
    deadline = datetime.now(timezone.utc) + timedelta(minutes=10)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_ttd", "status": "flashing", "deadline": _iso(deadline)},
    )

    client = EdgeLensClient(api_key="test_key")
    sess = client.create_session()
    remaining = sess.time_to_deadline()
    assert remaining is not None
    # Roughly 10 minutes; loose bound for clock jitter.
    assert timedelta(minutes=9) < remaining < timedelta(minutes=11)


def test_time_to_deadline_none_when_no_server_deadline(httpx_mock):
    """helper returns None when the server never sent a deadline
    (an older api version)."""
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_no_ttd", "status": "flashing"},
    )
    client = EdgeLensClient(api_key="test_key")
    sess = client.create_session()
    assert sess.time_to_deadline() is None


def test_async_time_to_deadline_matches_sync(httpx_mock):
    """AsyncSession.time_to_deadline mirrors sync."""
    deadline = datetime.now(timezone.utc) + timedelta(seconds=45)
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_ttd_a", "status": "flashing", "deadline": _iso(deadline)},
    )

    async def run() -> Optional[timedelta]:
        client = AsyncEdgeLensClient(api_key="test_key")
        sess = await client.create_session()
        return sess.time_to_deadline()

    ttd = asyncio.run(run())
    assert ttd is not None and timedelta(seconds=30) < ttd < timedelta(seconds=60)


def test_no_deadline_field_still_allows_ready_transition(httpx_mock):
    """An older api version that omits `deadline`: safety net does NOT fire
    when the session becomes READY within it. Backwards-compat is
    strictly for the transient window while all apis roll to the
    server-deadline contract."""
    from edgelens import session as session_mod

    # Safety net stays at its real value; we just don't need to hit it.
    httpx_mock.add_response(
        method="POST",
        url="https://api.edgelens.ai/v1/sessions",
        json={"id": "sess_backcompat", "status": "flashing"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_backcompat",
        json={
            "id": "sess_backcompat",
            "status": "ready",
            "device": {
                "mac": "aa:bb:cc:00:00:03",
                "host": "10.0.0.7",
                "ssh_user": "recamera",
                "ssh_password": "x" * 20,
                "os": "stock-os",
            },
        },
    )

    client = EdgeLensClient(api_key="test_key")
    sess = client.create_session()
    ready = sess.wait_ready(poll_interval=0.01)
    assert ready.status.value == "ready"
