import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_edgelens_env(monkeypatch):
    """Strip ambient ``EDGELENS_*`` env vars before each test.

    A developer who sourced a local ``.env`` has ``EDGELENS_BASE_URL`` /
    ``EDGELENS_API_KEY`` (and possibly ``EDGELENS_MCP_*``) exported. Without
    this, the server construction and SSH-detail helpers pick up ambient values
    instead of the hermetic test setup. Tests that exercise a specific var set
    it explicitly.
    """
    for key in list(os.environ):
        if key.startswith("EDGELENS_"):
            monkeypatch.delenv(key, raising=False)
