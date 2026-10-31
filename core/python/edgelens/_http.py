"""Internal HTTP transport. Wraps httpx with EdgeLens auth, retries, and error mapping."""

from __future__ import annotations

import ipaddress
import os
import random
import re
import socket
import time
from typing import Any, Iterable, Iterator, Optional, Union

import httpx

from edgelens._version import __version__
from edgelens.errors import (
    AuthenticationError,
    EdgeLensError,
    SessionError,
)


DEFAULT_BASE_URL = "https://api.edgelens.ai"
DEFAULT_TIMEOUT = 30.0

# exec and inference results hold the request open for the requested time;
# the api adds its own 15 s upstream margin, so the client waits longer still.
OP_READ_MARGIN_S = 30.0


def op_read_timeout(client_timeout: float, op_seconds: float) -> float:
    """Read timeout for a request held open ``op_seconds`` by the api.
    Never lower than the client's configured timeout."""
    return max(client_timeout, op_seconds + OP_READ_MARGIN_S)


def _allow_private_base_url() -> bool:
    """Allow a base URL on a private or loopback address, for example a
    local test server. Off by default; opt in with ``EDGELENS_ALLOW_PRIVATE_BASE_URL`` set to
    a truthy value."""
    return os.environ.get("EDGELENS_ALLOW_PRIVATE_BASE_URL", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _nets(*cidrs: str) -> tuple:
    return tuple(ipaddress.ip_network(c) for c in cidrs)


# The base URL host denylist. The TypeScript client carries the same tables
# (core/typescript/src/baseurl.ts) and both suites run the shared cases in
# core/testdata/base_url_hosts.json. The ranges are spelled out rather than
# taken from ipaddress's is_private and friends, whose tables change between
# Python releases.
#
# Refused even with EDGELENS_ALLOW_PRIVATE_BASE_URL: link-local, multicast,
# unspecified, reserved, and the IPv6 instance metadata address.
_V4_REFUSED = _nets("169.254.0.0/16", "224.0.0.0/4", "0.0.0.0/32", "240.0.0.0/4")
_V6_REFUSED = _nets(
    "fe80::/10", "ff00::/8", "::/128", "fd00:ec2::254/128",
    "::/8", "100::/8", "200::/7", "400::/6", "800::/5", "1000::/4", "4000::/3",
    "6000::/3", "8000::/3", "a000::/3", "c000::/3", "e000::/4", "f000::/5",
    "f800::/6", "fe00::/9",
)
# Refused unless EDGELENS_ALLOW_PRIVATE_BASE_URL is set: loopback,
# private-use, shared address space and the special-purpose blocks.
_V4_PRIVATE = _nets(
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "172.16.0.0/12",
    "192.0.0.0/24", "192.0.0.170/31", "192.0.2.0/24", "192.168.0.0/16",
    "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
)
_V4_PRIVATE_EXCEPT = _nets("192.0.0.9/32", "192.0.0.10/32")
_V6_PRIVATE = _nets(
    "::1/128", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32",
    "2002::/16", "3fff::/20", "fc00::/7",
)
_V6_PRIVATE_EXCEPT = _nets(
    "2001:1::1/128", "2001:1::2/128", "2001:3::/32", "2001:4:112::/48",
    "2001:20::/28", "2001:30::/28",
)
_LEGACY_IPV4 = re.compile(r"[0-9a-fx.]+")


def _parse_host_ip(host: str) -> Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """The address a host literal names, or None for a DNS name.

    Also reads the legacy IPv4 forms the system resolver accepts and a URL
    parser following WHATWG normalises (``127.1``, ``2130706433``,
    ``0x7f000001``), so they cannot slip past as names.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _LEGACY_IPV4.fullmatch(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            pass
    return None


def _classify_host(hostname: str) -> str:
    """``"public"``, ``"private"`` or ``"refused"`` for a URL hostname."""
    host = hostname.lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.endswith("."):
        host = host[:-1]
    if host == "localhost" or host.endswith(".localhost"):
        return "private"
    ip = _parse_host_ip(host)
    if ip is None:
        return "public"
    # Judge ::ffff:10.0.0.1 as 10.0.0.1.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address):
        refused, private, exceptions = _V4_REFUSED, _V4_PRIVATE, _V4_PRIVATE_EXCEPT
    else:
        ip = ipaddress.IPv6Address(int(ip))  # drop any %scope
        refused, private, exceptions = _V6_REFUSED, _V6_PRIVATE, _V6_PRIVATE_EXCEPT
    if any(ip in n for n in refused):
        return "refused"
    if any(ip in n for n in private) and not any(ip in n for n in exceptions):
        return "private"
    return "public"


def _validate_base_url(url: str, *, allow_insecure: bool = False) -> str:
    """Refuse base URLs that would exfiltrate the Bearer token.

    Rejects:
    - Non-http(s) schemes (file://, gopher://, ...).
    - http:// unless ``allow_insecure=True`` (silent TLS downgrade). This
      does not relax the host check.
    - Link-local (incl. the 169.254.169.254 and fd00:ec2::254 cloud
      metadata addresses), multicast, unspecified and reserved addresses:
      always, no override.
    - Loopback, private-use, shared (100.64.0.0/10) and other
      special-purpose addresses, and ``localhost``: unless the operator sets
      ``EDGELENS_ALLOW_PRIVATE_BASE_URL=1``, for example to reach a local
      test server. It never relaxes the first group, and applies to a
      ``base_url`` the operator controls. The check reads the host as
      written: a hostname is not resolved here, so a name that resolves to
      a private address is not caught by it.
    - Empty hostnames.

    The ranges are the tables above. Returns the URL with trailing slash
    stripped on success; raises AuthenticationError on failure with a
    customer-actionable message.
    """
    from urllib.parse import urlsplit

    if not url:
        raise AuthenticationError("base_url is empty")

    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise AuthenticationError(
            f"base_url scheme {scheme!r} not allowed (use http or https)"
        )
    if scheme == "http" and not allow_insecure:
        raise AuthenticationError(
            "base_url uses http:// — Bearer token would be sent in cleartext. "
            "Pass allow_insecure_base_url=True if this is a local dev loop."
        )
    host = parsed.hostname or ""
    if not host:
        raise AuthenticationError("base_url is missing a host")

    # The check applies to the host as written; a DNS name is resolved
    # only when the request is made.
    kind = _classify_host(host)
    if kind == "refused":
        raise AuthenticationError(
            f"base_url host {host} is a link-local/reserved "
            "address — refusing to send Bearer token there."
        )
    if kind == "private" and not _allow_private_base_url():
        raise AuthenticationError(
            f"base_url host {host} is a private/loopback address. If this "
            "is a server you run, such as a local test server, set "
            "EDGELENS_ALLOW_PRIVATE_BASE_URL=1 to allow it — only for a "
            "base_url you control (it relaxes an SSRF/token-exfil guard)."
        )

    return url.rstrip("/")


# An error body is the server's text: from a hostile or compromised api, or a
# proxy in front of it, it can be arbitrarily long and carry anything. Error
# messages keep at most this many characters of it, with control characters
# replaced, before it reaches a log, a terminal or an LLM transcript.
MAX_ERROR_MESSAGE_CHARS = 512
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def bound_message(text: str) -> str:
    """``text`` with control characters replaced by a space, cut to
    ``MAX_ERROR_MESSAGE_CHARS``."""
    flat = _CONTROL_CHARS.sub(" ", text).strip()
    if len(flat) <= MAX_ERROR_MESSAGE_CHARS:
        return flat
    extra = len(flat) - MAX_ERROR_MESSAGE_CHARS
    return f"{flat[:MAX_ERROR_MESSAGE_CHARS]}... ({extra} more characters)"


def _error_message(response: httpx.Response) -> str:
    """The server's message for an error response, bounded."""
    msg: Any = None
    try:
        data = response.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
    except Exception:
        pass
    if not isinstance(msg, str) or not msg:
        msg = response.text or response.reason_phrase
    return bound_message(msg)


def encode_path_param(value: str) -> str:
    """URL-quote a path parameter so a
    crafted value like ``../accounts/me/keys/shadow`` cannot escape
    the intended path. Server-side defenses also exist, but the SDK
    should not rely on them.

    ``safe=""`` so even forward slashes get percent-encoded — there
    are no legitimate slashes in a session id. ``.`` and ``..`` are
    refused: a URL parser resolves them as dot segments even when encoded.
    """
    from urllib.parse import quote
    if value in ("", ".", ".."):
        raise EdgeLensError(f"invalid path parameter: {value!r}")
    return quote(value, safe="")


# Connection pool defaults — picked to support a handful of concurrent
# sessions per process without burying the platform API in keepalives.
DEFAULT_MAX_CONNECTIONS = 20
DEFAULT_MAX_KEEPALIVE = 10

# Retry policy: idempotent methods only (so a retried POST never duplicates
# a session). Retry on transport errors and gateway-style 5xx/429.
_RETRY_METHODS = {"GET", "DELETE", "HEAD", "OPTIONS"}
_RETRY_STATUSES = {429, 502, 503, 504}
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 0.5  # seconds; multiplied by 2**attempt + jitter


class RetryPolicy:
    """When + how to retry an idempotent request.

    Pass a custom instance to ``HTTPClient`` (or ``EdgeLensClient``) to
    raise the cap, disable retries (max_attempts=1), or change the cadence.
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        max_delay: float = 30.0,
        retry_statuses: Iterable[int] = _RETRY_STATUSES,
        retry_methods: Iterable[str] = _RETRY_METHODS,
    ):
        self.max_attempts = max(1, int(max_attempts))
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.retry_statuses = set(retry_statuses)
        self.retry_methods = {m.upper() for m in retry_methods}

    def should_retry(self, method: str, status: Optional[int], attempt: int) -> bool:
        if attempt + 1 >= self.max_attempts:
            return False
        if method.upper() not in self.retry_methods:
            return False
        if status is None:  # transport-level failure
            return True
        return status in self.retry_statuses

    def delay_for(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self.max_delay)
        # Decorrelated exponential backoff with jitter.
        cap = min(self.base_delay * (2 ** attempt), self.max_delay)
        return random.uniform(self.base_delay, cap)


def _parse_retry_after(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # RFC 7231 also allows HTTP-date; we don't bother parsing.
        return None


class HTTPClient:
    """Authenticated HTTP client for the platform API.

    Configures connection pooling, an idempotent retry policy, and
    streams file uploads so multi-hundred-MB OS images don't sit in RAM.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE,
        retry_policy: Optional[RetryPolicy] = None,
        allow_insecure_base_url: bool = False,
    ):
        # Scheme + host validation before pinning the Bearer into headers.
        # Without it, a malicious EDGELENS_BASE_URL would receive the
        # Bearer: the header is forwarded unchanged to whatever host the
        # URL points at.
        self._base_url = _validate_base_url(
            base_url, allow_insecure=allow_insecure_base_url
        )
        self._retry = retry_policy or RetryPolicy()
        self.timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": f"edgelens-python/{__version__}",
            },
            # Never follow
            # 3xx automatically; an attacker-controlled redirect target
            # would otherwise re-receive the Bearer.
            follow_redirects=False,
        )
        # Do NOT keep ``api_key`` as a
        # public/long-lived attribute. The Authorization header is the
        # only persistent reference. close() overwrites it.

    def request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        files: Optional[dict] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        """``timeout`` sets the read timeout for this request only; the
        other phases keep the client's configured value."""
        response = self._send_with_retry(
            method, path, json=json, params=params, files=files, timeout=timeout
        )
        return self._handle_response(response, path)

    def _send_with_retry(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        files: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        attempt = 0
        last_exc: Optional[Exception] = None
        extra = {} if timeout is None else {"timeout": httpx.Timeout(self.timeout, read=timeout)}
        while True:
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json if files is None else None,
                    params=params,
                    files=files,
                    data=json if files is not None else None,
                    **extra,
                )
            except httpx.HTTPError as e:
                last_exc = e
                if not self._retry.should_retry(method, status=None, attempt=attempt):
                    raise EdgeLensError(f"HTTP transport error: {bound_message(str(e))}") from e
                time.sleep(self._retry.delay_for(attempt))
                attempt += 1
                continue

            if not self._retry.should_retry(method, response.status_code, attempt):
                return response
            time.sleep(self._retry.delay_for(attempt, retry_after=_parse_retry_after(response)))
            attempt += 1

    def _handle_response(self, response: httpx.Response, path: str) -> Any:
        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired API key")
        if response.status_code == 403:
            raise AuthenticationError(
                f"API key does not have permission: {self._error_message(response)}"
            )
        if response.status_code == 404:
            raise SessionError(f"Resource not found: {path}")
        if response.status_code >= 400:
            raise EdgeLensError(
                f"API error {response.status_code}: {self._error_message(response)}"
            )

        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.content

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Optional[dict] = None,
        files: Optional[dict] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        return self.request("POST", path, json=json, files=files, timeout=timeout)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def stream(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        chunk_size: int = 65_536,
        max_bytes: Optional[int] = 1_073_741_824,  # 1 GiB
        max_duration_s: Optional[float] = 600.0,
    ) -> Iterator[bytes]:
        """Yield raw chunks from a streaming endpoint.

        No retries (the body has already started being consumed by the
        time most failures surface). 4xx/5xx still surface as exceptions
        before the first chunk yields.

        Per-call caps so a hostile or
        compromised platform cannot OOM / hang the consumer process.
        - ``max_bytes`` — total bytes across all yields. ``None`` disables.
        - ``max_duration_s`` — wall-clock from the first chunk. ``None``
          disables.
        Both default to comfortable values; callers can pass ``None`` for
        legitimate multi-GiB downloads (OS image fetches).
        """
        with self._client.stream(method, path, params=params) as response:
            self._handle_response_headers_only(response, path)
            total = 0
            start = time.monotonic()
            for chunk in response.iter_bytes(chunk_size):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise EdgeLensError(
                        f"stream exceeded max_bytes ({max_bytes:,}); aborted "
                        f"after {total:,} bytes"
                    )
                if max_duration_s is not None:
                    elapsed = time.monotonic() - start
                    if elapsed > max_duration_s:
                        raise EdgeLensError(
                            f"stream exceeded max_duration_s ({max_duration_s}); "
                            f"aborted after {elapsed:.1f}s"
                        )
                yield chunk

    def _handle_response_headers_only(self, response: httpx.Response, path: str) -> None:
        """Raise on 4xx/5xx without consuming the body."""
        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired API key")
        if response.status_code == 403:
            raise AuthenticationError("API key does not have permission")
        if response.status_code == 404:
            raise SessionError(f"Resource not found: {path}")
        if response.status_code >= 400:
            raise EdgeLensError(f"API error {response.status_code}")

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        return _error_message(response)


class AsyncHTTPClient:
    """httpx.AsyncClient mirror of HTTPClient — same surface, awaitable."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE,
        retry_policy: Optional[RetryPolicy] = None,
        allow_insecure_base_url: bool = False,
    ):
        # Async sibling of HTTPClient.
        self._base_url = _validate_base_url(
            base_url, allow_insecure=allow_insecure_base_url
        )
        self._retry = retry_policy or RetryPolicy()
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": f"edgelens-python/{__version__}",
            },
            follow_redirects=False,
        )

    async def request(
        self,
        method: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        files: Optional[dict] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        """``timeout`` sets the read timeout for this request only; the
        other phases keep the client's configured value."""
        import asyncio

        attempt = 0
        extra = {} if timeout is None else {"timeout": httpx.Timeout(self.timeout, read=timeout)}
        while True:
            try:
                response = await self._client.request(
                    method,
                    path,
                    json=json if files is None else None,
                    params=params,
                    files=files,
                    data=json if files is not None else None,
                    **extra,
                )
            except httpx.HTTPError as e:
                if not self._retry.should_retry(method, status=None, attempt=attempt):
                    raise EdgeLensError(f"HTTP transport error: {bound_message(str(e))}") from e
                await asyncio.sleep(self._retry.delay_for(attempt))
                attempt += 1
                continue

            if not self._retry.should_retry(method, response.status_code, attempt):
                return _handle_async_response(response, path)
            await asyncio.sleep(self._retry.delay_for(attempt, retry_after=_parse_retry_after(response)))
            attempt += 1

    async def get(self, path: str, params: Optional[dict] = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(
        self,
        path: str,
        json: Optional[dict] = None,
        files: Optional[dict] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Any:
        return await self.request("POST", path, json=json, files=files, timeout=timeout)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    async def stream(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        chunk_size: int = 65_536,
        max_bytes: Optional[int] = 1_073_741_824,  # 1 GiB
        max_duration_s: Optional[float] = 600.0,
    ):
        """Async generator yielding raw chunks. Per-call
        max_bytes / max_duration_s caps, same shape as
        the sync sibling."""
        async with self._client.stream(method, path, params=params) as response:
            _raise_for_status_headers_only(response, path)
            total = 0
            start = time.monotonic()
            async for chunk in response.aiter_bytes(chunk_size):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise EdgeLensError(
                        f"stream exceeded max_bytes ({max_bytes:,}); aborted "
                        f"after {total:,} bytes"
                    )
                if max_duration_s is not None:
                    elapsed = time.monotonic() - start
                    if elapsed > max_duration_s:
                        raise EdgeLensError(
                            f"stream exceeded max_duration_s ({max_duration_s}); "
                            f"aborted after {elapsed:.1f}s"
                        )
                yield chunk

    async def aclose(self) -> None:
        await self._client.aclose()


def _handle_async_response(response: httpx.Response, path: str) -> Any:
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired API key")
    if response.status_code == 403:
        raise AuthenticationError("API key does not have permission")
    if response.status_code == 404:
        raise SessionError(f"Resource not found: {path}")
    if response.status_code >= 400:
        raise EdgeLensError(f"API error {response.status_code}: {_error_message(response)}")
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.content


def _raise_for_status_headers_only(response: httpx.Response, path: str) -> None:
    if response.status_code == 401:
        raise AuthenticationError("Invalid or expired API key")
    if response.status_code == 403:
        raise AuthenticationError("API key does not have permission")
    if response.status_code == 404:
        raise SessionError(f"Resource not found: {path}")
    if response.status_code >= 400:
        raise EdgeLensError(f"API error {response.status_code}")
