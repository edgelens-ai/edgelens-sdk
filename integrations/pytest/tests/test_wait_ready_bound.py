"""The plugin's default allocation path (no wait timeout) terminates.

EdgelensOptions defaults wait_ready_timeout_s to None, so the SDK's
client-side maximum wait is the only bound when the api keeps the session
pending with a deadline it never reaches. Shrunk here so the test is fast;
the session is released on the way out.
"""

from __future__ import annotations

import pytest

from edgelens import EdgeLensClient
from edgelens import session as session_mod
from edgelens.errors import TimeoutError as ELTimeoutError
from pytest_edgelens.lifecycle import EdgelensOptions, allocate_session


def test_default_allocation_stops_and_releases(httpx_mock, monkeypatch):
    monkeypatch.setattr(session_mod, "_SAFETY_NET_S", 0.1)
    pending = {"id": "sess_hang", "status": "pending", "deadline": "9000-01-01T00:00:00Z"}
    httpx_mock.add_response(
        method="POST", url="https://api.edgelens.ai/v1/sessions", json=pending,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/sessions/sess_hang",
        json=pending,
        is_reusable=True,
    )
    httpx_mock.add_response(
        method="DELETE",
        url="https://api.edgelens.ai/v1/sessions/sess_hang",
        status_code=204,
    )

    opts = EdgelensOptions(poll_interval_s=0.01)
    assert opts.wait_ready_timeout_s is None
    with pytest.raises(ELTimeoutError, match="client-side maximum wait"):
        allocate_session(EdgeLensClient(api_key="k"), opts)

    assert httpx_mock.get_requests()[-1].method == "DELETE"
