"""max_bytes / max_duration_s caps on stream APIs.
"""

from __future__ import annotations

import pytest

from edgelens.errors import EdgeLensError


def test_httpclient_stream_aborts_when_max_bytes_exceeded(httpx_mock):
    """The sync HTTPClient.stream must
    raise EdgeLensError when the cap is hit."""
    from edgelens._http import HTTPClient

    big_chunk = b"a" * 200
    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/data",
        content=big_chunk * 50,  # 10 KiB
    )
    client = HTTPClient(api_key="k")
    gen = client.stream("GET", "/v1/data", chunk_size=200, max_bytes=300)
    out = []
    with pytest.raises(EdgeLensError, match="max_bytes"):
        for chunk in gen:
            out.append(chunk)
    # We got at least one chunk before the abort.
    assert len(out) >= 1


def test_httpclient_stream_disabled_when_max_bytes_none(httpx_mock):
    """Passing None disables the cap — legitimate multi-GiB OS image
    downloads still work."""
    from edgelens._http import HTTPClient

    httpx_mock.add_response(
        method="GET",
        url="https://api.edgelens.ai/v1/data",
        content=b"a" * 5000,
    )
    client = HTTPClient(api_key="k")
    total = sum(len(c) for c in client.stream(
        "GET", "/v1/data", chunk_size=200, max_bytes=None,
    ))
    assert total == 5000
