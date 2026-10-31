"""Top-level EdgeLens client. Entry point for creating sessions."""

from __future__ import annotations

import os
from typing import Optional, Union

from edgelens._http import DEFAULT_BASE_URL, HTTPClient, RetryPolicy, encode_path_param
from edgelens.errors import AuthenticationError
from edgelens.session import Session
from edgelens.types import DeviceType, OSType


class EdgeLensClient:
    """Entry point for the EdgeLens Edge AI Device Farm.

    Args:
        api_key: API key. If not provided, reads from EDGELENS_API_KEY env var.
        base_url: Override the platform API base URL. If not provided, reads from EDGELENS_BASE_URL
            env var, then falls back to DEFAULT_BASE_URL. Precedence:
            explicit arg > env var > default.
        timeout: Default HTTP request timeout in seconds.
        max_connections: httpx connection-pool cap.
        max_keepalive_connections: httpx keepalive cap.
        retry_policy: override the default retry policy for idempotent ops.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
        retry_policy: Optional[RetryPolicy] = None,
        allow_insecure_base_url: bool = False,
    ):
        api_key = api_key or os.environ.get("EDGELENS_API_KEY")
        if not api_key:
            raise AuthenticationError(
                "No API key provided. Pass api_key=... or set EDGELENS_API_KEY."
            )
        # Use `is None` (not `or`) so an explicit base_url="" still
        # reaches the validator and raises loudly (the base_url validation contract).
        if base_url is None:
            base_url = os.environ.get("EDGELENS_BASE_URL") or DEFAULT_BASE_URL

        # Forward the allow_insecure flag
        # through so the http:// downgrade fails loudly by default.
        self._http = HTTPClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            retry_policy=retry_policy,
            allow_insecure_base_url=allow_insecure_base_url,
        )

    def create_session(
        self,
        device_type: Union[DeviceType, str] = DeviceType.RECAMERA_2002,
        os: Union[OSType, str] = OSType.STOCK,
        timeout: int = 3600,
        image_version: Optional[str] = None,
    ) -> Session:
        """Request a new device session.

        The session is allocated and provisioned asynchronously. Call
        ``session.wait_ready()`` before using the device.

        Args:
            device_type: Type of device to allocate.
            os: Which OS to flash on the device.
            timeout: Max session duration in seconds.
            image_version: OS image version to flash. When ``None``,
                the platform picks its default.

        Returns:
            A Session object. Not yet ready — call wait_ready() before use.
        """
        device_type = DeviceType(device_type) if isinstance(device_type, str) else device_type
        os_type = OSType(os) if isinstance(os, str) else os

        payload = {
            "device_type": device_type.value,
            "os": os_type.value,
            "timeout": timeout,
        }
        if image_version is not None:
            payload["image_version"] = image_version
        data = self._http.post("/v1/sessions", json=payload)
        return Session._from_api(data, http=self._http)

    def get_session(self, session_id: str) -> Session:
        """Retrieve an existing session by ID."""
        data = self._http.get(f"/v1/sessions/{encode_path_param(session_id)}")
        return Session._from_api(data, http=self._http)

    def close(self) -> None:
        """Close the HTTP client. Active sessions are not released."""
        self._http.close()

    def __enter__(self) -> "EdgeLensClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
