"""Internal HTTP transport. Wraps httpx with EdgeLens auth, retries, and error mapping."""

from __future__ import annotations

import os
import random
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
    """Escape hatch for self-hosted deployments reached by a private/loopback
    IP. Off by default; opt in with ``EDGELENS_ALLOW_PRIVATE_BASE_URL`` set to
    a truthy value."""
    return os.environ.get("EDGELENS_ALLOW_PRIVATE_BASE_URL", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _validate_base_url(url: str, *, allow_insecure: bool = False) -> str:
    """Refuse base URLs that would exfiltrate the Bearer token.

    Rejects:
    - Non-http(s) schemes (file://, gopher://, ...).
    - http:// unless ``allow_insecure=True`` (silent TLS downgrade).
    - Link-local (incl. 169.254.169.254 cloud IMDS), multicast,
      unspecified, reserved addresses — always, no override.
    - Loopback + RFC1918 private addresses — unless the operator sets
      ``EDGELENS_ALLOW_PRIVATE_BASE_URL=1``. That escape hatch exists for
      a self-hosted api reached by LAN IP; it only relaxes loopback +
      RFC1918, never IMDS/link-local, and applies to a ``base_url`` the
      operator controls. Note the guard is host-literal only — a
      hostname that *resolves* to a private IP is not caught here (DNS
      pinning is the platform's job), so this is defense-in-depth, not a
      complete SSRF boundary.
    - Empty hostnames.

    Returns the URL with trailing slash stripped on success; raises
    AuthenticationError on failure with a customer-actionable message.
    """
    from urllib.parse import urlsplit
    import ipaddress

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

    # Literal IPs — apply the private-IP filter.
    try:
        ip = ipaddress.ip_address(host)
        # Unwrap IPv4-mapped IPv6 so ::ffff:10.0.0.1 is judged as 10.0.0.1
        # by the same filter as a plain IPv4 literal.
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        # IMDS/link-local, multicast, unspecified, reserved are never a
        # legitimate api host — refuse unconditionally.
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise AuthenticationError(
                f"base_url host {host} is a link-local/reserved "
                "address — refusing to send Bearer token there."
            )
        # Loopback + RFC1918 are legitimate for self-hosted LAN
        # deployments, but a token-exfil risk otherwise — refuse unless
        # the operator explicitly opts in for a base_url they control.
        if (ip.is_loopback or ip.is_private) and not _allow_private_base_url():
            raise AuthenticationError(
                f"base_url host {host} is a private/loopback address. If this "
                "is a self-hosted EdgeLens api on your network, set "
                "EDGELENS_ALLOW_PRIVATE_BASE_URL=1 to allow it — only for a "
                "base_url you control (it relaxes an SSRF/token-exfil guard)."
            )
    except ValueError:
        # Not a literal IP — caller resolves via DNS at request time.
        # We don't pre-resolve here because the SDK lives in the customer
        # process; DNS pinning is the platform's job.
        pass

    return url.rstrip("/")


def encode_path_param(value: str) -> str:
    """URL-quote a path parameter so a
    crafted value like ``../accounts/me/keys/shadow`` cannot escape
    the intended path. Server-side defenses also exist, but the SDK
    should not rely on them.

    ``safe=""`` so even forward slashes get percent-encoded — there
    are no legitimate slashes in a session id.
    """
    from urllib.parse import quote
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
                    raise EdgeLensError(f"HTTP transport error: {e}") from e
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
        try:
            data = response.json()
            return data.get("message") or data.get("error") or response.text
        except Exception:
            return response.text or response.reason_phrase


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
                    raise EdgeLensError(f"HTTP transport error: {e}") from e
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
        try:
            data = response.json()
            msg = data.get("message") or data.get("error") or response.text
        except Exception:
            msg = response.text or response.reason_phrase
        raise EdgeLensError(f"API error {response.status_code}: {msg}")
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
