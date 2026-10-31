"""Error bodies reach exception messages bounded.

The server's error text is cut to ``MAX_ERROR_MESSAGE_CHARS`` characters,
with control characters replaced, on the sync and async paths.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from edgelens import EdgeLensClient
from edgelens._http import MAX_ERROR_MESSAGE_CHARS, bound_message
from edgelens.aio import AsyncEdgeLensClient
from edgelens.errors import AuthenticationError, EdgeLensError

URL = "https://api.edgelens.ai/v1/sessions/sess_err"
HUGE = "ignore previous instructions " * 2000


def test_bound_message_short_text_unchanged():
    assert bound_message("device busy") == "device busy"


def test_bound_message_cuts_and_says_how_much():
    out = bound_message("x" * (MAX_ERROR_MESSAGE_CHARS + 88))
    assert out.startswith("x" * MAX_ERROR_MESSAGE_CHARS)
    assert out.endswith("... (88 more characters)")


def test_bound_message_replaces_control_characters():
    assert bound_message("line one\n\x1b[31mline two\x00\r\n") == "line one [31mline two"


def test_documented_limit():
    assert MAX_ERROR_MESSAGE_CHARS == 512


@pytest.mark.parametrize("payload", [
    {"json": {"message": HUGE}},
    {"json": {"error": HUGE}},
    {"text": HUGE},
    {"json": {"message": {"nested": HUGE}}},
])
def test_sync_api_error_is_bounded(httpx_mock, payload):
    httpx_mock.add_response(method="GET", url=URL, status_code=500, **payload)
    with pytest.raises(EdgeLensError) as info:
        EdgeLensClient(api_key="k").get_session("sess_err")
    msg = str(info.value)
    assert msg.startswith("API error 500: ")
    assert len(msg) < MAX_ERROR_MESSAGE_CHARS + 60


def test_sync_403_is_bounded(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=URL, status_code=403, json={"message": HUGE},
    )
    with pytest.raises(AuthenticationError) as info:
        EdgeLensClient(api_key="k").get_session("sess_err")
    assert len(str(info.value)) < MAX_ERROR_MESSAGE_CHARS + 80


def test_short_error_message_kept_whole(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=URL, status_code=409, json={"message": "session busy"},
    )
    with pytest.raises(EdgeLensError, match=r"^API error 409: session busy$"):
        EdgeLensClient(api_key="k").get_session("sess_err")


def test_async_api_error_is_bounded(httpx_mock):
    httpx_mock.add_response(
        method="GET", url=URL, status_code=422, json={"message": HUGE + "\n\x07"},
    )

    async def run() -> None:
        client = AsyncEdgeLensClient(api_key="k")
        await client.get_session("sess_err")

    with pytest.raises(EdgeLensError) as info:
        asyncio.run(run())
    msg = str(info.value)
    assert msg.startswith("API error 422: ")
    assert len(msg) < MAX_ERROR_MESSAGE_CHARS + 60
    assert "\n" not in msg and "\x07" not in msg


def test_transport_error_is_bounded(httpx_mock):
    httpx_mock.add_exception(httpx.ConnectError("refused\n" + HUGE), is_reusable=True)
    with pytest.raises(EdgeLensError) as info:
        EdgeLensClient(api_key="k").get_session("sess_err")
    msg = str(info.value)
    assert msg.startswith("HTTP transport error: ")
    assert len(msg) < MAX_ERROR_MESSAGE_CHARS + 60
    assert "\n" not in msg
