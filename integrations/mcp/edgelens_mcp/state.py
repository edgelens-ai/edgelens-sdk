"""Server-side state: lazily-constructed SDK client, session cache, current-session pointer.

The MCP protocol is stateless from the host's perspective — each tool call is a
fresh request. We keep an in-process cache of the EdgeLens client and any
sessions we've allocated so follow-up tools don't have to reconstruct them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from edgelens import EdgeLensClient, Session

ALLOW_EXTERNAL_SESSIONS_ENV = "EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS"


def external_sessions_allowed() -> bool:
    return os.environ.get(ALLOW_EXTERNAL_SESSIONS_ENV) == "1"


@dataclass
class ServerState:
    _client: Optional[EdgeLensClient] = None
    _sessions: dict[str, Session] = field(default_factory=dict)
    _current_session_id: Optional[str] = None

    def client(self) -> EdgeLensClient:
        """Return the singleton SDK client, building it on first call."""
        if self._client is None:
            api_key = os.environ.get("EDGELENS_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "EDGELENS_API_KEY env var is not set. Configure it in your "
                    "MCP client's server config (e.g. Claude Desktop's "
                    "claude_desktop_config.json `env` block)."
                )
            kwargs: dict = {"api_key": api_key}
            base_url = os.environ.get("EDGELENS_BASE_URL")
            if base_url:
                kwargs["base_url"] = base_url
            self._client = EdgeLensClient(**kwargs)
        return self._client

    def remember(self, session: Session) -> None:
        """Store a Session so follow-up tools can use it by id, and set current."""
        self._sessions[session.id] = session
        self._current_session_id = session.id

    def get(self, session_id: Optional[str]) -> Session:
        """Resolve a session id (or the current-session pointer) to a Session.

        Only sessions this process created are resolved by default. An id
        it did not create is fetched from the API only when the operator
        set ``EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS=1``; otherwise it raises
        ValueError naming that opt-in. The API key may reach sessions owned
        by teammates on a shared account, and the model must not release
        or exec on those by guessing or being handed an id.
        """
        sid = session_id or self._current_session_id
        if sid is None:
            raise ValueError(
                "No session id and no current session. Call `create_session` "
                "or pass `session_id` explicitly."
            )
        existing = self._sessions.get(sid)
        if existing is not None:
            return existing
        if not external_sessions_allowed():
            raise ValueError(
                f"session {sid} was not created by this MCP server, so it "
                "is refused. Tools act only on sessions this server created. "
                f"To resume another session, the operator must set "
                f"{ALLOW_EXTERNAL_SESSIONS_ENV}=1 in the MCP host env."
            )
        session = self.client().get_session(sid)
        self._sessions[sid] = session
        return session

    def forget(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self._current_session_id == session_id:
            self._current_session_id = None

    @property
    def current_session_id(self) -> Optional[str]:
        return self._current_session_id

    def list_session_ids(self) -> list[str]:
        return list(self._sessions.keys())


# Module-level singleton; the server.py decorators capture it.
STATE = ServerState()
