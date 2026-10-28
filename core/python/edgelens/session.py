"""Session lifecycle management."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from edgelens._http import HTTPClient, encode_path_param
from edgelens.device import Device
from edgelens.errors import SessionError, TimeoutError
from edgelens.types import DeviceConnection, OSType, SessionStatus


# safety-net ceiling for wait_ready when the server returns no
# `deadline` field at all (older api, broken response). Should never
# fire when talking to a current api version. Module-level so tests
# can monkey-patch to a small value without waiting 30 real minutes.
_SAFETY_NET_S: float = 30 * 60

# grace period past the server's `deadline` before wait_ready
# gives up. The platform flips a stuck session to ERROR on
# the tick after `deadline`; we wait that long so the platform's
# actual error reason (from db.error_message) surfaces on the next
# poll — rather than the SDK speculatively raising a generic
# "did not become ready by server deadline" SessionError that loses
# the real cause. Module-level so tests can shorten it.
_DEADLINE_GRACE_S: float = 30


def _parse_deadline(raw: Optional[str]) -> Optional[datetime]:
    """Parse the server-returned ISO-8601 ``deadline`` field.

    returns None when the server omits it (an older api version).
    Handles trailing 'Z' for Python 3.9's fromisoformat which won't
    accept it natively.

    coerces naive datetimes to UTC — some api response paths
    (notably the SQLite dev backend) round-trip tzinfo away, so a
    subsequent GET may return a bare "2026-08-30T15:47:58" string
    while POST returned "...Z"-suffixed. Comparing the two in
    ``refresh``'s monotonicity guard would `TypeError`. Assume UTC
    for tz-less inputs — the api's own contract is "UTC deadlines
    always", so this can't misinterpret an offset the server meant
    to communicate.
    """
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Session state machine. Refresh rejects
# transitions not in this map. Terminal states are absent → nothing
# can transition out of them.
_FORWARD_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.PENDING: {
        SessionStatus.PENDING, SessionStatus.ALLOCATING,
        SessionStatus.ERROR, SessionStatus.EXPIRED,
    },
    SessionStatus.ALLOCATING: {
        SessionStatus.ALLOCATING, SessionStatus.FLASHING,
        SessionStatus.ERROR, SessionStatus.EXPIRED,
    },
    SessionStatus.FLASHING: {
        SessionStatus.FLASHING, SessionStatus.READY,
        SessionStatus.ERROR, SessionStatus.EXPIRED,
    },
    SessionStatus.READY: {
        SessionStatus.READY,
        SessionStatus.RELEASED, SessionStatus.EXPIRED, SessionStatus.ERROR,
    },
    # Terminal states stay terminal.
    SessionStatus.RELEASED: {SessionStatus.RELEASED, SessionStatus.EXPIRED},
    SessionStatus.EXPIRED: {SessionStatus.EXPIRED},
    SessionStatus.ERROR: {SessionStatus.ERROR},
}


def _check_forward_transition(
    prev: SessionStatus, new: SessionStatus, session_id: str,
) -> None:
    allowed = _FORWARD_TRANSITIONS.get(prev, set())
    if new not in allowed:
        raise SessionError(
            f"Session {session_id}: server reported state {new.value!r} "
            f"which is not a forward transition from {prev.value!r}. "
            "Refusing to trust the response."
        )


class Session:
    """A device session — represents an allocated device for a customer test run.

    Sessions go through these states:
        pending → allocating → flashing → ready → released

    The ``device`` attribute is None until the session is ``ready``.
    """

    def __init__(
        self,
        session_id: str,
        status: SessionStatus,
        http: HTTPClient,
        connection: Optional[DeviceConnection] = None,
        expires_at: Optional[str] = None,
        deadline: Optional[datetime] = None,
    ):
        self.id = session_id
        self.status = status
        self.expires_at = expires_at
        # server-side readiness deadline from a current api version. None
        # when the api is on an older version or when the response omits it.
        # Kept as a public attribute so callers can inspect it.
        self.deadline = deadline
        self._http = http
        self._connection = connection
        self._device: Optional[Device] = None

        if connection is not None:
            self._device = Device(http=http, session_id=session_id, connection=connection)

    @classmethod
    def _from_api(cls, data: dict, http: HTTPClient) -> "Session":
        connection = None
        if "device" in data and data["device"]:
            connection = DeviceConnection.model_validate(data["device"])

        return cls(
            session_id=data["id"],
            status=SessionStatus(data["status"]),
            http=http,
            connection=connection,
            expires_at=data.get("expires_at"),
            deadline=_parse_deadline(data.get("deadline")),
        )

    @property
    def device(self) -> Device:
        """The device for this session.

        Raises SessionError if the session is not yet ready.
        """
        if self._device is None:
            raise SessionError(
                f"Session {self.id} is not ready (status={self.status.value}). "
                "Call wait_ready() first."
            )
        return self._device

    @property
    def os(self) -> Optional[OSType]:
        return self._connection.os if self._connection else None

    def refresh(self) -> "Session":
        """Re-fetch session state from the API.

        Validate the transition against
        a forward-only state machine, so a malicious or buggy server
        cannot flip a session backwards (RELEASED → READY, etc.) and
        silently clear `_device`.
        """
        data = self._http.get(f"/v1/sessions/{encode_path_param(self.id)}")
        new = Session._from_api(data, self._http)
        _check_forward_transition(self.status, new.status, self.id)
        self.status = new.status
        self.expires_at = new.expires_at
        # Preserve _device when the server temporarily drops it on a
        # status that doesn't itself imply a wipe (e.g. a transient
        # 'flashing' between two 'ready' polls during a hot-reflash).
        # Backward state transitions are caught above.
        self._connection = new._connection or self._connection
        self._device = new._device or self._device
        # deadline is monotonically non-decreasing per the server's
        # contract. If the server suddenly returns an earlier deadline
        # (buggy or malicious), keep the previously-observed one.
        if new.deadline is not None:
            if self.deadline is None or new.deadline >= self.deadline:
                self.deadline = new.deadline
        return self

    def wait_ready(
        self,
        timeout: Optional[float] = None,
        poll_interval: float = 2.0,
    ) -> "Session":
        """Block until the session is ready or fails.

        server-driven. The server's ``deadline`` field is the
        primary stopping condition — the platform commits to a moment
        by which the session must be READY, and the platform flips
        the row to ERROR when that commitment is missed. The client
        polls until READY / ERROR / EXPIRED / server deadline expires.

        Args:
            timeout: Client-side override in seconds. Default ``None``
                trusts the server's deadline. Pass an explicit value
                for testing or abort-early — it is a *ceiling*, not a
                floor, so it only shortens the wait (never extends
                past the server deadline).
            poll_interval: Seconds between status checks.

        Raises:
            SessionError: Session entered ERROR / EXPIRED / RELEASED,
                OR the server's deadline expired (plus a small grace
                period, see ``_DEADLINE_GRACE_S``) without the platform
                flipping the row to ERROR — treated as a stuck platform
                rather than the SDK speculating about the cause.
            TimeoutError: The explicit ``timeout=`` ceiling fired, OR
                the safety-net fired because the server returned no
                deadline (an older api version or broken response).
        """
        started_at = time.monotonic()
        while True:
            self.refresh()
            if self.status == SessionStatus.READY:
                return self
            if self.status in (SessionStatus.ERROR, SessionStatus.EXPIRED, SessionStatus.RELEASED):
                raise SessionError(
                    f"Session {self.id} ended in state {self.status.value} before becoming ready"
                )

            elapsed = time.monotonic() - started_at
            if timeout is not None and elapsed >= timeout:
                raise TimeoutError(
                    f"Session {self.id} did not become ready within "
                    f"caller-specified timeout={timeout}s (status={self.status.value})"
                )
            # wait a grace period past the server's deadline
            # before giving up — the platform will flip the
            # row to ERROR on its next tick and we'd rather surface
            # the platform's own error reason than raise a speculative
            # SessionError here.
            if (
                self.deadline is not None
                and datetime.now(timezone.utc)
                >= self.deadline + timedelta(seconds=_DEADLINE_GRACE_S)
            ):
                raise SessionError(
                    f"Session {self.id} passed server deadline "
                    f"{self.deadline.isoformat()} + {_DEADLINE_GRACE_S}s grace "
                    f"without the platform flipping it to ERROR "
                    f"(status={self.status.value}). The platform may be "
                    "stuck preparing this session; contact support with this session id."
                )
            if (
                self.deadline is None
                and timeout is None
                and elapsed >= _SAFETY_NET_S
            ):
                raise TimeoutError(
                    f"Session {self.id} did not become ready within safety-net "
                    f"{_SAFETY_NET_S}s and the server returned no ``deadline`` field. "
                    "Is the api on an older version?"
                )
            time.sleep(poll_interval)

    def time_to_deadline(self) -> Optional[timedelta]:
        """how long until the server-committed readiness deadline
        (positive) or how long past it (negative). ``None`` when the
        server returned no ``deadline`` (an older api version). Useful for
        progress-bar UIs on top of the SDK — the SDK itself uses this
        value implicitly in ``wait_ready``.
        """
        if self.deadline is None:
            return None
        return self.deadline - datetime.now(timezone.utc)

    def release(self) -> None:
        """End the session and return the device to the pool."""
        if self.status == SessionStatus.RELEASED:
            return
        self._http.delete(f"/v1/sessions/{encode_path_param(self.id)}")
        self.status = SessionStatus.RELEASED

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
