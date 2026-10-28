"""Unit tests for lifecycle helpers (no pytester required)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pytest_edgelens.lifecycle import (
    EdgelensOptions,
    allocate_session,
    release_session,
)


def test_allocate_session_calls_create_and_wait():
    client = MagicMock()
    session = MagicMock()
    client.create_session.return_value = session

    out = allocate_session(
        client,
        EdgelensOptions(
            api_key="k", os="stock-os", device_type="recamera-2002",
            session_timeout_s=900, wait_ready_timeout_s=120, poll_interval_s=1.0,
        ),
    )
    assert out is session
    client.create_session.assert_called_once_with(
        device_type="recamera-2002", os="stock-os", timeout=900,
        image_version=None,
    )
    session.wait_ready.assert_called_once_with(timeout=120, poll_interval=1.0)


def test_allocate_session_forwards_image_version():
    client = MagicMock()
    client.create_session.return_value = MagicMock()

    allocate_session(
        client,
        EdgelensOptions(api_key="k", image_version="0.2.3"),
    )
    _, kwargs = client.create_session.call_args
    assert kwargs["image_version"] == "0.2.3"


def test_edgelens_options_wait_ready_default_is_server_driven():
    """the dataclass default is now None — the
    SDK trusts the server-signaled `deadline` rather than a
    hardcoded client-side constant. Preserves the *option* to override
    (integer value threads through to Session.wait_ready as a ceiling)."""
    assert EdgelensOptions().wait_ready_timeout_s is None


def test_release_session_is_noop_for_none():
    release_session(None)  # must not raise


def test_release_session_swallows_release_errors(caplog: pytest.LogCaptureFixture):
    import logging

    session = MagicMock()
    session.release.side_effect = RuntimeError("teardown blew up")
    with caplog.at_level(logging.WARNING, logger="pytest_edgelens.lifecycle"):
        release_session(session)  # must not raise
    assert any("release failed" in rec.message for rec in caplog.records)


def test_allocate_propagates_wait_ready_errors():
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = RuntimeError("never came up")
    client.create_session.return_value = session

    with pytest.raises(RuntimeError, match="never came up"):
        allocate_session(client, EdgelensOptions(api_key="k"))


def test_allocate_releases_session_when_wait_ready_fails():
    """if wait_ready raises, the caller never receives the
    session object, so the fixture's finally-release never runs and
    the api-side session leaks until the server-side ~1h timeout —
    blocking the next allocation with a max_concurrent_sessions
    violation. allocate_session releases synchronously before
    re-raising to prevent that."""
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = RuntimeError("flash blew up")
    client.create_session.return_value = session

    with pytest.raises(RuntimeError, match="flash blew up"):
        allocate_session(client, EdgelensOptions(api_key="k"))

    session.release.assert_called_once()


def test_allocate_swallows_release_error_when_wait_ready_fails(
    caplog: pytest.LogCaptureFixture,
):
    """a secondary release failure during exception cleanup
    must not mask the primary wait_ready error — log the release
    failure and re-raise the original."""
    import logging

    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = RuntimeError("flash blew up")
    session.release.side_effect = RuntimeError("release also blew up")
    client.create_session.return_value = session

    with caplog.at_level(logging.WARNING, logger="pytest_edgelens.lifecycle"):
        with pytest.raises(RuntimeError, match="flash blew up"):
            allocate_session(client, EdgelensOptions(api_key="k"))

    assert any("release failed during allocate_session" in rec.message
               for rec in caplog.records)


# ---- an interrupted wait must not strand the device -------------------------
#
# The wait prints nothing and can run for half an hour, so the likeliest
# way it ever ends early is an operator pressing Ctrl-C at a silent
# terminal. KeyboardInterrupt is not an Exception, so a guard written to
# stop a session leaking will miss the only trigger anyone has actually
# seen it need — and the cost is the device held until the server-side
# timeout, on a bench with one usable camera.
#
# Every test below asserts that the release happened, not merely that the
# interrupt arrived. The interrupt arrives either way: it is raised inside
# the wait, so it reaches the caller whether or not anything caught it on
# the way out. Only the release call distinguishes a guard that fired from
# one that was never entered.
#
# These were checked by removing the guard and running them, which is the
# only way to know an assertion can fail. A test that still passes with
# the thing it pins removed is making no claim about it — and the pass
# column is the only place that shows, which is how two tests that could
# not fail survived a round of review here.


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_allocate_releases_the_session_when_the_wait_is_interrupted(interrupt):
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = interrupt()
    client.create_session.return_value = session

    with pytest.raises(interrupt):
        allocate_session(client, EdgelensOptions(api_key="k"))

    session.release.assert_called_once()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_an_interrupt_still_reaches_the_caller_after_the_release(interrupt):
    """Releasing must not turn an interrupt into a pass.

    pytest has its own handling for both of these and swallowing one
    here would strand the run instead of the device, which is worse
    than leaking the session.
    """
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = interrupt()
    client.create_session.return_value = session

    raised = None
    try:
        allocate_session(client, EdgelensOptions(api_key="k"))
    except BaseException as e:  # noqa: BLE001
        raised = e
    assert type(raised) is interrupt
    session.release.assert_called_once()


def test_an_ordinary_error_is_still_caught_by_the_same_guard():
    # Widening to BaseException must not change the behaviour that was
    # already right.
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = ValueError("ordinary")
    client.create_session.return_value = session

    with pytest.raises(ValueError, match="ordinary"):
        allocate_session(client, EdgelensOptions(api_key="k"))

    session.release.assert_called_once()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_a_second_interrupt_during_the_release_is_not_swallowed(interrupt):
    """The inner guard stays narrow, and this is why.

    An interrupt arriving while the release is in flight is the
    operator insisting. There is nothing left to protect by then, and
    turning it into a log line would leave them pressing Ctrl-C at a
    process that has decided to keep going.

    The release call is asserted, not just the propagation. Without it
    this passes against a guard that never caught anything at all: the
    interrupt would come straight out of the wait, the release would
    never be reached, and the inner guard this test is named for would
    not have run.
    """
    client = MagicMock()
    session = MagicMock()
    session.wait_ready.side_effect = interrupt()
    session.release.side_effect = interrupt()
    client.create_session.return_value = session

    with pytest.raises(interrupt):
        allocate_session(client, EdgelensOptions(api_key="k"))

    session.release.assert_called_once()


def test_the_successful_path_still_returns_the_live_session():
    """Why this is not a try/finally.

    A `finally` would release on the success path too — the path that
    hands the live session to the test — so every run would get a
    device that was released the moment it became ready.
    """
    client = MagicMock()
    session = MagicMock()
    client.create_session.return_value = session

    assert allocate_session(client, EdgelensOptions(api_key="k")) is session
    session.release.assert_not_called()
