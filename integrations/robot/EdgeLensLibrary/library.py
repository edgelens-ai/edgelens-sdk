"""``EdgeLensLibrary`` — the keyword-driven Robot Framework surface.

Designed for the SUITE scope (one device per suite by default — cheaper
than per-test allocation, matches the pytest plugin's session scope).
Pass ``scope=TEST`` at import time for per-test sessions when tests
mutate device state.

Usage::

    *** Settings ***
    Library    EdgeLensLibrary    api_key=%{EDGELENS_API_KEY}

    *** Test Cases ***
    Camera Renders The Test Pattern
        Request Device    os=stock-os
        Deploy Model    ${MODEL_PATH}
        Start Inference
        ${stats}=    Run Inference    duration=30
        Should Be True    ${stats.fps.avg} > 15
        [Teardown]    Release Device
"""

from __future__ import annotations

import os
from typing import Any, Optional

from edgelens import EdgeLensClient, Session
from edgelens.errors import EdgeLensError
from robot.api.deco import keyword, library

from EdgeLensLibrary._version import __version__


@library(scope="SUITE", auto_keywords=False, version=__version__)
class EdgeLensLibrary:
    """Keyword-driven Robot Framework interface to the EdgeLens SDK.

    Constructor arguments (set on the ``Library    EdgeLensLibrary`` line):

    - ``api_key``: API key. Defaults to ``$EDGELENS_API_KEY``.
    - ``base_url``: Override the platform base URL.
    - ``scope``: Library scope — ``SUITE`` (default), ``TEST``, or ``GLOBAL``.

    Set scope via the import line:

    ::

        Library    EdgeLensLibrary    scope=TEST
    """

    ROBOT_LIBRARY_VERSION = __version__
    ROBOT_AUTO_KEYWORDS = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        scope: str = "SUITE",
    ):
        # Robot translates the keyword scope into ROBOT_LIBRARY_SCOPE
        # at class level; @library(scope=...) handles the static case
        # but we expose it via constructor for late binding too.
        self.__class__.ROBOT_LIBRARY_SCOPE = scope.upper()  # type: ignore[attr-defined]

        self._api_key = api_key or os.environ.get("EDGELENS_API_KEY")
        self._base_url = base_url
        self._client: Optional[EdgeLensClient] = None
        self._session: Optional[Session] = None

    # ------------------------------------------------------------------
    # Internal plumbing
    # ------------------------------------------------------------------

    def _ensure_client(self) -> EdgeLensClient:
        if self._client is None:
            kwargs: dict[str, Any] = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = EdgeLensClient(**kwargs)
        return self._client

    def _require_session(self) -> Session:
        if self._session is None:
            raise EdgeLensError(
                "No active device session. Call `Request Device` first."
            )
        return self._session

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    @keyword("Request Device")
    def request_device(
        self,
        device_type: str = "recamera-2002",
        os: str = "stock-os",
        timeout: int = 3600,
        wait_timeout: int = 300,
    ) -> str:
        """Allocate a device and wait for ``status=ready``.

        Returns the session id. The allocated session is stored on the
        library instance — subsequent keywords (`Deploy Model`,
        `Execute On Device`, ...) target it implicitly.

        Example::

            Request Device    device_type=recamera-2002    os=stock-os
        """
        client = self._ensure_client()
        try:
            session = client.create_session(
                device_type=device_type, os=os, timeout=int(timeout),
            )
        except ValueError as e:
            raise EdgeLensError(f"Request Device failed: {e}") from e
        session.wait_ready(timeout=int(wait_timeout))
        self._session = session
        return session.id

    @keyword("Release Device")
    def release_device(self) -> None:
        """End the active session and return the device to the pool.

        No-op when there's no active session — safe to call from
        ``[Teardown]`` even on failed setup.
        """
        if self._session is None:
            return
        try:
            self._session.release()
        finally:
            self._session = None

    @keyword("Get Session Id")
    def get_session_id(self) -> str:
        return self._require_session().id

    @keyword("Get Session Status")
    def get_session_status(self) -> str:
        session = self._require_session()
        session.refresh()
        return session.status.value

    # ------------------------------------------------------------------
    # Device operations
    # ------------------------------------------------------------------

    @keyword("Execute On Device")
    def execute_on_device(self, command: str, timeout: float = 60.0) -> dict:
        """Run ``command`` via SSH (proxied). Returns a dict with
        ``stdout``, ``stderr``, ``exit_code``. Raises on transport
        failure (use ``Run Keyword And Ignore Error`` if you want soft
        handling).
        """
        result = self._require_session().device.exec(command, timeout=float(timeout))
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
        }

    @keyword("Deploy Model")
    def deploy_model(
        self,
        model: str,
        config: Optional[str] = None,
        files: Optional[list] = None,
    ) -> dict:
        """Deploy a model file (and optional config + extra files) to the device.

        On reCamaginedOS, files land in /userdata/Models/ readable but not
        executable; ``chmod +x`` a deployed binary before running it.
        """
        return dict(
            self._require_session().device.deploy(model=model, config=config, files=files)
        )

    @keyword("Get SSH Details")
    def get_ssh_details(self) -> dict:
        """Return SSH connection details (user/host/port).

        The password is NOT included by
        default. Robot Framework's log.html / output.xml record
        keyword return values verbatim, so returning the password
        here would leak it to CI artifacts.

        Use ``Get SSH Password`` (separate keyword) to retrieve the
        cleartext when needed; that keyword writes at TRACE level so
        the secret stays out of log.html unless the operator bumped
        log level for debugging.
        """
        creds = self._require_session().device.ssh()
        return {
            "user": creds.user,
            "host": creds.host,
            "port": creds.port,
        }

    @keyword("Get SSH Password", tags=["secret"])
    def get_ssh_password(self) -> str:
        """Return the SSH password as a string.

        This keyword is tagged
        ``secret`` and uses ``logger.write(..., level='TRACE',
        html=False)`` so the value does not land in log.html /
        output.xml at default verbosity. Treat log.html as sensitive
        when this keyword is used.
        """
        from robot.api import logger as _logger

        creds = self._require_session().device.ssh()
        _logger.write(
            "<SSH password retrieved via Get SSH Password>",
            level="TRACE", html=False,
        )
        return creds.password

    @keyword("Get Device Info")
    def get_device_info(self) -> dict:
        info = self._require_session().device.info()
        if hasattr(info, "model_dump"):
            return info.model_dump()
        return dict(getattr(info, "__dict__", {}))

    @keyword("Get Stream URL")
    def get_stream_url(self) -> str:
        return self._require_session().device.stream_url()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @keyword("Play On Display")
    def play_on_display(self, source: str, loop: bool = False) -> None:
        self._require_session().device.display.play(source, loop=bool(loop))

    @keyword("Show On Display")
    def show_on_display(self, source: str) -> None:
        self._require_session().device.display.show(source)

    @keyword("Stop Display")
    def stop_display(self) -> None:
        self._require_session().device.display.stop()

    @keyword("Get Display Status")
    def get_display_status(self) -> dict:
        return dict(self._require_session().device.display.status())

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    @keyword("Start Inference")
    def start_inference(self) -> None:
        self._require_session().device.inference.start()

    @keyword("Stop Inference")
    def stop_inference(self) -> None:
        self._require_session().device.inference.stop()

    @keyword("Run Inference Once")
    def run_inference_once(self) -> dict:
        return dict(self._require_session().device.inference.once())

    @keyword("Get Inference Stats")
    def get_inference_stats(self) -> dict:
        snap = self._require_session().device.inference.snapshot()
        if hasattr(snap, "model_dump"):
            return snap.model_dump()
        return dict(getattr(snap, "__dict__", {}))

    @keyword("Run Inference")
    def run_inference(self, duration: float = 30.0, collect_frames: bool = False) -> dict:
        """Run inference for ``duration`` seconds, return aggregated stats."""
        stats = self._require_session().device.inference.run(
            duration=float(duration), collect_frames=bool(collect_frames)
        )
        if hasattr(stats, "model_dump"):
            return stats.model_dump()
        return dict(getattr(stats, "__dict__", {}))
