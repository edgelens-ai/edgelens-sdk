import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_edgelens_env(monkeypatch):
    """Strip ambient ``EDGELENS_*`` env vars before each test.

    A developer who sourced a local ``.env`` has ``EDGELENS_BASE_URL`` /
    ``EDGELENS_API_KEY`` exported in their shell. Without this, the client
    picks up the real base URL and sends to it instead of the mocked
    ``api.edgelens.ai`` host — pytest-httpx then fails on unmatched/unconsumed
    responses. Tests that exercise env handling set what they need explicitly.
    """
    for key in list(os.environ):
        if key.startswith("EDGELENS_"):
            monkeypatch.delenv(key, raising=False)
