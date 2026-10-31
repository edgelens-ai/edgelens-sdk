"""Server-side state: lazily-constructed SDK client, session cache, current-session pointer.

The MCP protocol is stateless from the host's perspective — each tool call is a
fresh request. We keep an in-process cache of the EdgeLens client and any
sessions we've allocated so follow-up tools don't have to reconstruct them.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from edgelens import EdgeLensClient, Session

ALLOW_EXTERNAL_SESSIONS_ENV = "EDGELENS_MCP_ALLOW_EXTERNAL_SESSIONS"

logger = logging.getLogger(__name__)


def external_sessions_allowed() -> bool:
    return os.environ.get(ALLOW_EXTERNAL_SESSIONS_ENV) == "1"


@dataclass
class ServerState:
    _client: Optional[EdgeLensClient] = None
    _sessions: dict[str, Session] = field(default_factory=dict)
    _current_session_id: Optional[str] = None
    # Ids this process created. Only these are released on shutdown and
    # counted against the session limit: an external session resumed under
    # the opt-in may belong to a teammate.
    _owned_ids: set[str] = field(default_factory=set)

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
        self._owned_ids.add(session.id)
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
        self._owned_ids.discard(session_id)
        if self._current_session_id == session_id:
            self._current_session_id = None

    @property
    def current_session_id(self) -> Optional[str]:
        return self._current_session_id

    def list_session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def owned_count(self) -> int:
        """Number of sessions this process created and has not released."""
        return len(self._owned_ids)

    def release_owned(self) -> None:
        """Release, best effort, every session this process created.

        Called on server shutdown so a session the model never released
        does not stay allocated and billed until the platform's timeout.
        Failures are logged, never raised, so one bad release does not
        skip the rest. Each id is forgotten, which makes a second call a
        no-op.
        """
        for sid in list(self._owned_ids):
            session = self._sessions.get(sid)
            if session is not None:
                try:
                    session.release()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("shutdown release of session %s failed: %s", sid, exc)
                else:
                    logger.warning("released session %s on shutdown", sid)
            self.forget(sid)


# Module-level singleton; the server.py decorators capture it.
STATE = ServerState()
