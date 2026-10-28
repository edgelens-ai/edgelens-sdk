"""Async EdgeLens client — mirrors the sync surface using asyncio + httpx.AsyncClient.

Usage::

    import asyncio
    from edgelens.aio import AsyncEdgeLensClient

    async def main():
        async with AsyncEdgeLensClient(api_key="...") as client:
            session = await client.create_session(device_type="recamera-2002")
            await session.wait_ready()
            await session.device.deploy(model="./face.cvimodel")
            await session.release()

    asyncio.run(main())

The async surface is a strict subset of the sync one — the
DisplayController/InferenceController controllers and stream(...) are
covered; helper time.sleep loops become asyncio.sleep.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Optional, Union

from edgelens._http import (
    AsyncHTTPClient,
    DEFAULT_BASE_URL,
    RetryPolicy,
    encode_path_param,
    op_read_timeout,
)
from edgelens.errors import AuthenticationError, DeviceError, SessionError, TimeoutError
from edgelens import session as _session_mod
from edgelens.device import _safe_open
from edgelens.session import _parse_deadline
from edgelens.types import (
    DeviceConnection,
    DeviceInfo,
    DeviceType,
    InferenceSnapshot,
    InferenceStats,
    OSType,
    SessionStatus,
    SSHCredentials,
)


class AsyncEdgeLensClient:
    """Async entry point. Same shape as ``EdgeLensClient`` but every
    method is a coroutine.
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
        # mirror the sync client's env-fallback. Precedence:
        # explicit arg > EDGELENS_BASE_URL > DEFAULT_BASE_URL.
        # `is None` (not `or`) so an explicit "" still hits the
        # validator (the base_url validation contract).
        if base_url is None:
            base_url = os.environ.get("EDGELENS_BASE_URL") or DEFAULT_BASE_URL
        self._http = AsyncHTTPClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            allow_insecure_base_url=allow_insecure_base_url,
            retry_policy=retry_policy,
        )

    async def create_session(
        self,
        device_type: Union[DeviceType, str] = DeviceType.RECAMERA_2002,
        os: Union[OSType, str] = OSType.STOCK,
        timeout: int = 3600,
        image_version: Optional[str] = None,
    ) -> "AsyncSession":
        device_type = DeviceType(device_type) if isinstance(device_type, str) else device_type
        os_type = OSType(os) if isinstance(os, str) else os
        payload = {
            "device_type": device_type.value,
            "os": os_type.value,
            "timeout": timeout,
        }
        if image_version is not None:
            payload["image_version"] = image_version
        data = await self._http.post("/v1/sessions", json=payload)
        return AsyncSession._from_api(data, http=self._http)

    async def get_session(self, session_id: str) -> "AsyncSession":
        data = await self._http.get(f"/v1/sessions/{encode_path_param(session_id)}")
        return AsyncSession._from_api(data, http=self._http)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncEdgeLensClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class AsyncSession:
    """Async session — mirrors ``Session`` but every transition is awaited."""

    def __init__(
        self,
        session_id: str,
        status: SessionStatus,
        http: AsyncHTTPClient,
        connection: Optional[DeviceConnection] = None,
        expires_at: Optional[str] = None,
        deadline: Optional[datetime] = None,
    ):
        self.id = session_id
        self.status = status
        self.expires_at = expires_at
        # server-side readiness deadline from a current api version. See sync mirror.
        self.deadline = deadline
        self._http = http
        self._connection = connection
        self._device: Optional[AsyncDevice] = None
        if connection is not None:
            self._device = AsyncDevice(http=http, session_id=session_id, connection=connection)

    @classmethod
    def _from_api(cls, data: dict, http: AsyncHTTPClient) -> "AsyncSession":
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
    def device(self) -> "AsyncDevice":
        if self._device is None:
            raise SessionError(
                f"Session {self.id} is not ready (status={self.status.value}). "
                "Call wait_ready() first."
            )
        return self._device

    async def refresh(self) -> "AsyncSession":
        data = await self._http.get(f"/v1/sessions/{encode_path_param(self.id)}")
        new = AsyncSession._from_api(data, self._http)
        self.status = new.status
        self.expires_at = new.expires_at
        self._connection = new._connection
        self._device = new._device
        # deadline monotonic per the server's contract.
        if new.deadline is not None:
            if self.deadline is None or new.deadline >= self.deadline:
                self.deadline = new.deadline
        return self

    async def wait_ready(
        self,
        timeout: Optional[float] = None,
        poll_interval: float = 2.0,
    ) -> "AsyncSession":
        """Async mirror of ``Session.wait_ready`` (server-driven).

        See the sync docstring for semantics — same server-deadline
        precedence and safety-net behavior; ``timeout`` remains as an
        explicit override for testing / abort-early.
        """
        loop = asyncio.get_event_loop()
        started_at = loop.time()
        while True:
            await self.refresh()
            if self.status == SessionStatus.READY:
                return self
            if self.status in (SessionStatus.ERROR, SessionStatus.EXPIRED, SessionStatus.RELEASED):
                raise SessionError(
                    f"Session {self.id} ended in state {self.status.value} before becoming ready"
                )

            elapsed = loop.time() - started_at
            if timeout is not None and elapsed >= timeout:
                raise TimeoutError(
                    f"Session {self.id} did not become ready within "
                    f"caller-specified timeout={timeout}s (status={self.status.value})"
                )
            # server_deadline + grace (attribute-lookup on the
            # session module so tests can monkey-patch the constant
            # and both sync + async pick it up).
            if (
                self.deadline is not None
                and datetime.now(timezone.utc)
                >= self.deadline + timedelta(seconds=_session_mod._DEADLINE_GRACE_S)
            ):
                raise SessionError(
                    f"Session {self.id} passed server deadline "
                    f"{self.deadline.isoformat()} + "
                    f"{_session_mod._DEADLINE_GRACE_S}s grace "
                    f"without the platform flipping it to ERROR "
                    f"(status={self.status.value}). The platform may be "
                    "stuck preparing this session; contact support with this session id."
                )
            if (
                self.deadline is None
                and timeout is None
                and elapsed >= _session_mod._SAFETY_NET_S
            ):
                raise TimeoutError(
                    f"Session {self.id} did not become ready within safety-net "
                    f"{_session_mod._SAFETY_NET_S}s and the server returned no "
                    "``deadline`` field. Is the api on an older version?"
                )
            await asyncio.sleep(poll_interval)

    def time_to_deadline(self) -> Optional[timedelta]:
        """async mirror of ``Session.time_to_deadline``. Returns
        ``deadline - now`` (positive when the platform still has time
        to reach READY, negative when past). ``None`` when the server
        returned no ``deadline`` (an older api version).
        """
        if self.deadline is None:
            return None
        return self.deadline - datetime.now(timezone.utc)

    async def release(self) -> None:
        if self.status == SessionStatus.RELEASED:
            return
        await self._http.delete(f"/v1/sessions/{encode_path_param(self.id)}")
        self.status = SessionStatus.RELEASED

    async def __aenter__(self) -> "AsyncSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()


class AsyncDevice:
    """Async device — covers the customer-facing operations.

    Display + inference subcontrollers are intentionally bare here;
    they re-issue HTTP calls one-shot rather than mirroring the sync
    wait_stable/wait_ready loops. Add them if a use case shows up.
    """

    def __init__(
        self,
        http: AsyncHTTPClient,
        session_id: str,
        connection: DeviceConnection,
    ):
        self._http = http
        self._session_id = session_id
        self._connection = connection

    @property
    def mac(self) -> str:
        return self._connection.mac

    @property
    def host(self) -> str:
        return self._connection.host

    @property
    def os(self) -> OSType:
        return self._connection.os

    async def deploy(
        self,
        model: Union[str, Path],
        config: Optional[Union[str, Path]] = None,
        files: Optional[list[Union[str, Path]]] = None,
    ) -> dict:
        """Deploy a model and optional supporting files to the device.

        On stock OS, the model is installed for the built-in inference API.
        On reCamaginedOS, the model and each file land in /userdata/Models/
        under their base filenames, readable but not executable: run
        ``chmod +x`` on a deployed binary before executing it.
        """
        # Honor the ``_allowed_upload_root``
        # path-jail like the sync client — a bare open() here let a
        # crafted path escape the root the sync side enforces.
        allowed_root = getattr(self, "_allowed_upload_root", None)
        with contextlib.ExitStack() as stack:
            payload_files: dict = {}
            payload_files["model"] = (
                Path(model).name,
                stack.enter_context(_safe_open(model, allowed_root)),
            )
            if config:
                payload_files["config"] = (
                    Path(config).name,
                    stack.enter_context(_safe_open(config, allowed_root)),
                )
            if files:
                for i, path in enumerate(files):
                    payload_files[f"file_{i}"] = (
                        Path(path).name,
                        stack.enter_context(_safe_open(path, allowed_root)),
                    )
            return await self._http.post(
                f"/v1/sessions/{encode_path_param(self._session_id)}/deploy",
                files=payload_files,
            )

    async def upload(self, local: Union[str, Path], remote: str) -> dict:
        """Removed: the platform has no arbitrary-path upload endpoint.
        Async mirror of ``Device.upload`` — see it for the migration."""
        raise DeviceError(
            "device.upload() is not supported — the platform has no "
            "arbitrary-path upload endpoint. Push files with "
            "device.deploy(model=..., files=[...]) (they land in "
            "/userdata/Models/ on reCamaginedOS), or copy to a specific "
            "path over SSH using device.ssh()."
        )

    async def exec(self, command: str, timeout: float = 60.0) -> dict:
        """Run a command on the device via SSH.

        The HTTP wait is extended to cover the requested command timeout.
        """
        payload = {"command": command, "timeout": timeout}
        return await self._http.post(
            f"/v1/sessions/{encode_path_param(self._session_id)}/exec",
            json=payload,
            timeout=op_read_timeout(self._http.timeout, timeout),
        )

    def ssh(self) -> SSHCredentials:
        return SSHCredentials(
            user=self._connection.ssh_user,
            host=self._connection.host,
            port=self._connection.ssh_port,
            password=self._connection.ssh_password,
        )

    async def info(self) -> DeviceInfo:
        data = await self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/info")
        return DeviceInfo.model_validate(data)

    async def stream_url(self) -> str:
        if self.os == OSType.RECAMAGINED:
            raise DeviceError(
                "reCamaginedOS does not provide a built-in camera stream."
            )
        data = await self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/stream")
        return data["url"]

    async def stream(
        self,
        chunk_size: int = 65_536,
        max_bytes: Optional[int] = 1_073_741_824,
        max_duration_s: Optional[float] = 600.0,
    ) -> AsyncIterator[bytes]:
        """Async generator yielding raw frame chunks. Async
        sibling of the sync variant, forwards the byte/time caps."""
        if self.os == OSType.RECAMAGINED:
            raise DeviceError(
                "reCamaginedOS does not provide a built-in camera stream."
            )
        async for chunk in self._http.stream(
            "GET",
            f"/v1/sessions/{encode_path_param(self._session_id)}/stream/raw",
            chunk_size=chunk_size,
            max_bytes=max_bytes,
            max_duration_s=max_duration_s,
        ):
            yield chunk
