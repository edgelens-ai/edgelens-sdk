"""wait_for_release timeout.
Session.refresh rejects backward transitions.
"""

from __future__ import annotations

import pytest

from edgelens.errors import SessionError, TimeoutError
from edgelens.session import _check_forward_transition
from edgelens.types import SessionStatus


# ---- forward-only state machine --------------------------------------


def test_check_forward_transition_allows_forward():
    _check_forward_transition(SessionStatus.PENDING, SessionStatus.ALLOCATING, "s1")
    _check_forward_transition(SessionStatus.FLASHING, SessionStatus.READY, "s1")
    _check_forward_transition(SessionStatus.READY, SessionStatus.RELEASED, "s1")


def test_check_forward_transition_allows_same_state():
    """Status unchanged across two polls is fine."""
    for s in SessionStatus:
        _check_forward_transition(s, s, "s1")


def test_check_forward_transition_rejects_backward():
    """Server can't flip a released session back to ready."""
    with pytest.raises(SessionError, match="forward transition"):
        _check_forward_transition(SessionStatus.RELEASED, SessionStatus.READY, "s1")


def test_check_forward_transition_rejects_skip_back_through_flashing():
    """ready → flashing without going through release would let a
    server silently reassign a customer's device."""
    with pytest.raises(SessionError):
        _check_forward_transition(SessionStatus.READY, SessionStatus.FLASHING, "s1")


def test_check_forward_transition_rejects_error_to_active():
    """Terminal error stays terminal."""
    with pytest.raises(SessionError):
        _check_forward_transition(SessionStatus.ERROR, SessionStatus.READY, "s1")


# ---- wait_for_release timeout ----------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_wait_for_release_raises_timeout(httpx_mock):
    """A hung platform that never returns a terminal
    status does not pin the consumer."""
    from edgelens import EdgeLensClient

    # Seed many "ready" polls; the loop never sees a terminal state.
    for _ in range(100):
        httpx_mock.add_response(
            method="GET",
            url="https://api.edgelens.ai/v1/sessions/sess_x",
            json={"id": "sess_x", "status": "ready"},
        )
    client = EdgeLensClient(api_key="k")
    from edgelens.device import Device
    from edgelens.types import DeviceConnection, OSType
    conn = DeviceConnection(
        mac="aa:bb:cc:00:00:01", host="10.0.0.1",
        ssh_port=22, ssh_user="recamera", ssh_password="x",
        web_ui=None, os=OSType.STOCK,
    )
    device = Device(http=client._http, session_id="sess_x", connection=conn)
    # 0.5s deadline so the test runs fast.
    with pytest.raises(TimeoutError, match="wait_for_release"):
        device.wait_for_release(timeout_s=0.5, poll_interval_s=0.1)
