"""Device interface — the primary surface customers use in tests."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Iterator, Optional, Union

from edgelens._http import HTTPClient, encode_path_param, op_read_timeout
from edgelens.errors import DeviceError, TimeoutError
from edgelens.types import (
    DeviceConnection,
    DeviceInfo,
    InferenceSnapshot,
    InferenceStats,
    OSType,
    SSHCredentials,
)


def _safe_open(path: Union[str, Path], allowed_root: Optional[Path]):
    """Open ``path`` while enforcing the
    ``allowed_root`` boundary when set.

    Without ``allowed_root`` set, behaves identically to ``open(path,
    'rb')`` — the existing customer contract. When set, resolves the
    path and refuses any target outside the root (including symlinks
    that escape it).
    """
    if allowed_root is None:
        return open(path, "rb")
    resolved = Path(path).resolve(strict=True)
    root = Path(allowed_root).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        raise DeviceError(
            f"refusing to open {path!r}: resolved path {resolved!s} is "
            f"not under allowed_upload_root {root!s}"
        ) from None
    return open(resolved, "rb")


class _DisplayController:
    """Control the per-device display via the platform API."""

    def __init__(self, http: HTTPClient, session_id: str):
        self._http = http
        self._session_id = session_id

    def play(self, file: Union[str, Path], loop: bool = False) -> None:
        """Play a video on the display.

        Args:
            file: Local path or URL (http(s)/s3://).
            loop: Loop the video continuously.
        """
        payload = {"source": str(file), "loop": loop}
        self._http.post(f"/v1/sessions/{encode_path_param(self._session_id)}/display/play", json=payload)

    def show(self, file: Union[str, Path]) -> None:
        """Show a static image on the display."""
        payload = {"source": str(file)}
        self._http.post(f"/v1/sessions/{encode_path_param(self._session_id)}/display/show", json=payload)

    def stop(self) -> None:
        """Stop display playback."""
        self._http.post(f"/v1/sessions/{encode_path_param(self._session_id)}/display/stop")

    def status(self) -> dict:
        """Current display state."""
        return self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/display/status")

    def wait_stable(self, timeout: float = 5.0, poll_interval: float = 0.5) -> None:
        """Wait for the display to settle into the requested state."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.status()
            if state.get("ready"):
                return
            time.sleep(poll_interval)
        raise TimeoutError(f"Display did not become stable within {timeout}s")


class _InferenceController:
    """Control inference on the device. Available on stock OS (the built-in inference API).

    On reCamaginedOS this raises DeviceError — use ``device.exec()`` to run
    customer-provided binaries instead.
    """

    def __init__(self, http: HTTPClient, session_id: str, os: OSType):
        self._http = http
        self._session_id = session_id
        self._os = os

    def _check_supported(self) -> None:
        if self._os == OSType.RECAMAGINED:
            raise DeviceError(
                "Built-in inference is not available on reCamaginedOS. "
                "Use device.exec() to run a customer-provided inference binary."
            )

    def start(self) -> None:
        self._check_supported()
        self._http.post(f"/v1/sessions/{encode_path_param(self._session_id)}/inference/start")

    def stop(self) -> None:
        self._check_supported()
        self._http.post(f"/v1/sessions/{encode_path_param(self._session_id)}/inference/stop")

    def once(self) -> dict:
        """Run a single inference frame and return the result."""
        self._check_supported()
        return self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/inference/once")

    def snapshot(self) -> InferenceSnapshot:
        """Current point-in-time metrics from a running inference."""
        self._check_supported()
        data = self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/inference/stats")
        return InferenceSnapshot.model_validate(data)

    def run(self, duration: float = 30.0, collect_frames: bool = False) -> InferenceStats:
        """Run inference for a duration and return aggregated stats.

        Args:
            duration: Seconds to run.
            collect_frames: If True, include per-frame detections in the result.

        The HTTP wait is extended to cover the requested duration.
        """
        self._check_supported()
        payload = {"duration_s": duration, "collect_frames": collect_frames}
        data = self._http.post(
            f"/v1/sessions/{encode_path_param(self._session_id)}/inference/results",
            json=payload,
            timeout=op_read_timeout(self._http.timeout, duration),
        )
        return InferenceStats.model_validate(data)

    def wait_ready(self, timeout: float = 30.0, poll_interval: float = 1.0) -> None:
        """Wait for the model to load and produce at least one frame."""
        self._check_supported()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                snap = self.snapshot()
                if snap.fps > 0:
                    return
            except DeviceError:
                pass
            time.sleep(poll_interval)
        raise TimeoutError(f"Inference did not become ready within {timeout}s")

    def stream(
        self, duration: float = 30.0, interval: float = 1.0
    ) -> Iterator[InferenceSnapshot]:
        """Yield inference snapshots periodically for the given duration."""
        self._check_supported()
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            yield self.snapshot()
            time.sleep(interval)


class _ExecResult:
    """Result of executing a command on the device."""

    def __init__(self, stdout: str, stderr: str, exit_code: int):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def __repr__(self) -> str:
        return f"ExecResult(exit_code={self.exit_code}, stdout={self.stdout[:80]!r})"


class Device:
    """The primary test surface — represents the allocated device.

    Methods are organized into namespaces:
        device.deploy(...)        — deploy a model + supporting files
        device.display.play(...)  — control the display
        device.inference.run(...) — run inference (stock OS only)
        device.exec(...)          — run a command via SSH
        device.ssh()              — get SSH connection details
        device.info()             — get device info report
    """

    def __init__(
        self,
        http: HTTPClient,
        session_id: str,
        connection: DeviceConnection,
    ):
        self._http = http
        self._session_id = session_id
        self._connection = connection
        self.display = _DisplayController(http, session_id)
        self.inference = _InferenceController(http, session_id, connection.os)

    @property
    def mac(self) -> str:
        return self._connection.mac

    @property
    def host(self) -> str:
        return self._connection.host

    @property
    def os(self) -> OSType:
        return self._connection.os

    @property
    def web_ui(self) -> Optional[str]:
        return self._connection.web_ui

    def deploy(
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

        File handles are streamed to the platform — full OS images don't
        sit in RAM.
        """
        # If the caller passes
        # ``allowed_root``, resolve every input path and reject any
        # that escape the root. Defense in depth — customer test code
        # that interpolates untrusted names into a path does not get
        # an arbitrary-read primitive via the SDK.
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
            return self._http.post(
                f"/v1/sessions/{encode_path_param(self._session_id)}/deploy",
                files=payload_files,
            )

    def upload(self, local: Union[str, Path], remote: str) -> dict:
        """Not supported: the platform has no arbitrary-path upload endpoint.

        Always raises ``DeviceError``. Push files with
        ``deploy(model=..., files=[...])`` (they land in
        ``/userdata/Models/`` on reCamaginedOS), or copy to a specific
        path over SSH using the credentials from ``ssh()``.
        """
        raise DeviceError(
            "device.upload() is not supported — the platform has no "
            "arbitrary-path upload endpoint. Push files with "
            "device.deploy(model=..., files=[...]) (they land in "
            "/userdata/Models/ on reCamaginedOS), or copy to a specific "
            "path over SSH using device.ssh()."
        )

    def exec(self, command: str, timeout: float = 60.0) -> _ExecResult:
        """Run a command on the device via SSH.

        The HTTP wait is extended to cover the requested command timeout.
        """
        payload = {"command": command, "timeout": timeout}
        data = self._http.post(
            f"/v1/sessions/{encode_path_param(self._session_id)}/exec",
            json=payload,
            timeout=op_read_timeout(self._http.timeout, timeout),
        )
        return _ExecResult(
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code", -1),
        )

    def ssh(self) -> SSHCredentials:
        """Get SSH connection details."""
        return SSHCredentials(
            user=self._connection.ssh_user,
            host=self._connection.host,
            port=self._connection.ssh_port,
            password=self._connection.ssh_password,
        )

    def info(self) -> DeviceInfo:
        """Get the device info report (collect_device_info.sh output)."""
        data = self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/info")
        return DeviceInfo.model_validate(data)

    def stream_url(self) -> str:
        """Get the camera stream URL.

        On stock OS, returns the camera's web UI WebSocket URL.
        On reCamaginedOS, raises DeviceError — no built-in stream.
        """
        if self.os == OSType.RECAMAGINED:
            raise DeviceError(
                "reCamaginedOS does not provide a built-in camera stream. "
                "Configure your own streaming in your test binary."
            )
        data = self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}/stream")
        return data["url"]

    def stream(
        self,
        chunk_size: int = 65_536,
        max_bytes: Optional[int] = 1_073_741_824,
        max_duration_s: Optional[float] = 600.0,
    ) -> Iterator[bytes]:
        """Yield raw frame chunks from the device's stream.

        Backed by the platform's stream proxy — stock OS only. Yields
        binary chunks of ``chunk_size`` bytes; caller decodes.

        Per-call ``max_bytes`` and
        ``max_duration_s`` caps forwarded to the underlying HTTP
        stream so a hostile / compromised platform cannot OOM or hang
        the consumer process. Pass ``None`` to disable a cap for
        legitimate multi-GiB or long-running fetches.

        Note: WebSocket upgrade isn't wired here yet. The current proxy
        serves MJPEG-style chunked HTTP; WS pass-through is a follow-up.
        """
        if self.os == OSType.RECAMAGINED:
            raise DeviceError(
                "reCamaginedOS does not provide a built-in camera stream."
            )
        yield from self._http.stream(
            "GET",
            f"/v1/sessions/{encode_path_param(self._session_id)}/stream/raw",
            chunk_size=chunk_size,
            max_bytes=max_bytes,
            max_duration_s=max_duration_s,
        )

    def wait_for_release(
        self, timeout_s: float = 1800.0, poll_interval_s: float = 5.0,
    ) -> None:
        """Block until the session is released externally.

        Per-call timeout cap. Without it the only exit would be a
        terminal status, so a hung or hostile platform could pin the
        consumer indefinitely.

        Default 1800s (30 min) covers normal interactive sessions
        with room to spare. Pass ``timeout_s=None`` to disable.
        """
        start = time.monotonic()
        while True:
            data = self._http.get(f"/v1/sessions/{encode_path_param(self._session_id)}")
            if data["status"] in ("released", "expired", "error"):
                return
            if timeout_s is not None and (time.monotonic() - start) > timeout_s:
                raise TimeoutError(
                    f"wait_for_release timed out after {timeout_s}s; "
                    f"session {self._session_id} is still in state "
                    f"{data.get('status')!r}"
                )
            time.sleep(poll_interval_s)
