"""Fixture lifecycle helpers — the actual session allocation + release
logic, kept separate from ``plugin.py`` so it can be unit-tested
without pytester.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields
from typing import Any, Optional

from edgelens import EdgeLensClient, Session

logger = logging.getLogger(__name__)


def _mask(api_key: Optional[str]) -> str:
    """Say whether a key is set, and nothing else about it.

    Any value derived from the key, a prefix or a digest alike, lets
    whoever reads the output confirm a guessed key offline.
    """
    return "None" if api_key is None else "<set>"


@dataclass
class EdgelensOptions:
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    device_type: str = "recamera-2002"
    os: str = "stock-os"
    image_version: Optional[str] = None
    session_timeout_s: int = 3600
    # None (default) trusts the server's `deadline` field;
    # an explicit int is a caller-supplied ceiling override.
    wait_ready_timeout_s: Optional[int] = None
    poll_interval_s: float = 2.0
    skip_allocation: bool = False

    def __repr__(self) -> str:
        # pytest renders fixture arguments when setup raises, so this
        # is what reaches a customer's CI log on a failed allocation.
        shown = [f"api_key={_mask(self.api_key)}"]
        shown += [
            f"{f.name}={getattr(self, f.name)!r}" for f in fields(self) if f.repr
        ]
        return f"{type(self).__name__}({', '.join(shown)})"


def build_client(opts: EdgelensOptions) -> EdgeLensClient:
    """Construct the underlying EdgeLensClient.

    Reads the API key from the options or falls through to the SDK's
    own env-var fallback (``EDGELENS_API_KEY``). The SDK raises
    ``AuthenticationError`` when neither is set; we let it propagate
    so pytest reports it as a fixture-setup failure with the right
    pointer.
    """
    kwargs: dict[str, Any] = {}
    if opts.api_key:
        kwargs["api_key"] = opts.api_key
    if opts.base_url:
        kwargs["base_url"] = opts.base_url
    return EdgeLensClient(**kwargs)


def allocate_session(client: EdgeLensClient, opts: EdgelensOptions) -> Session:
    """Create a session and wait for ready.

    Errors from create_session propagate directly. Anything raised by
    wait_ready triggers a synchronous ``session.release()`` before
    re-raising — otherwise the api-side session is orphaned (the
    fixture teardown only sees the return value, and there is no
    return value on the exceptional path) and it leaks until the
    server-side timeout (~1h), blocking the next allocation with
    ``max_concurrent_sessions`` violations.

    ``BaseException`` and not ``Exception``, because the likeliest way
    this wait ever ends early is someone pressing Ctrl-C, and
    ``KeyboardInterrupt`` is not an ``Exception``. The wait prints
    nothing and can run for half an hour, so an operator watching a
    silent terminal interrupts it long before it times out. A guard
    that caught only ``Exception`` would miss the most likely trigger
    and leak the session.

    A plain ``try``/``finally`` would be wrong here: this returns the
    live session on the success path, and a ``finally`` would release
    it the moment it became ready.
    """
    session = client.create_session(
        device_type=opts.device_type,
        os=opts.os,
        timeout=opts.session_timeout_s,
        image_version=opts.image_version,
    )
    try:
        session.wait_ready(
            timeout=opts.wait_ready_timeout_s,
            poll_interval=opts.poll_interval_s,
        )
    except BaseException:
        try:
            session.release()
        # Deliberately narrower than the guard above. A second
        # interrupt arriving while the release is in flight belongs to
        # the operator insisting, and must not be turned into a log
        # line — there is nothing left to protect by then anyway.
        except Exception as release_exc:  # noqa: BLE001
            logger.warning(
                "edgelens session release failed during allocate_session "
                "cleanup: %s (primary error follows)", release_exc,
            )
        raise
    return session


def release_session(session: Optional[Session]) -> None:
    """Release a session, swallowing teardown errors.

    A failed release shouldn't mask the actual test failure that
    happened before it — pytest already records the test outcome by
    the time fixture teardown runs.
    """
    if session is None:
        return
    try:
        session.release()
    except Exception as e:  # noqa: BLE001
        logger.warning("edgelens session release failed: %s", e)
