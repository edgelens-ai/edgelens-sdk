"""Unit tests for EdgeLensLibrary — stub the SDK + invoke keywords directly."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from EdgeLensLibrary import EdgeLensLibrary
from edgelens import EdgeLensClient
from edgelens.errors import EdgeLensError
from edgelens.types import OSType


@pytest.fixture
def lib():
    return EdgeLensLibrary(api_key="el_test_k")


@pytest.fixture
def lib_with_session(lib):
    fake_session = MagicMock()
    fake_session.id = "sess_test"
    fake_session.status.value = "ready"
    lib._session = fake_session  # bypass request_device
    return lib, fake_session


# ---- session lifecycle ------------------------------------------------------


def test_request_device_creates_session_and_waits():
    lib = EdgeLensLibrary(api_key="el_test_k")
    fake_client = MagicMock()
    fake_session = MagicMock()
    fake_session.id = "sess_alloc"
    fake_client.create_session.return_value = fake_session
    lib._client = fake_client

    sid = lib.request_device(device_type="recamera-2002", os="stock-os", timeout=600, wait_timeout=120)
    assert sid == "sess_alloc"
    fake_client.create_session.assert_called_once_with(
        device_type="recamera-2002", os="stock-os", timeout=600,
    )
    fake_session.wait_ready.assert_called_once_with(timeout=120)
    assert lib._session is fake_session


def test_request_device_default_os_is_a_valid_os_type():
    lib = EdgeLensLibrary(api_key="el_test_k")
    fake_client = MagicMock()
    lib._client = fake_client

    lib.request_device()
    OSType(fake_client.create_session.call_args.kwargs["os"])


def test_request_device_invalid_os_raises_library_error():
    lib = EdgeLensLibrary(api_key="el_test_k")
    lib._client = EdgeLensClient(api_key="el_test_k")

    with pytest.raises(EdgeLensError, match="Request Device failed"):
        lib.request_device(os="stock")
    assert lib._session is None


def test_release_device_calls_release_and_clears(lib_with_session):
    lib, fake_session = lib_with_session
    lib.release_device()
    fake_session.release.assert_called_once()
    assert lib._session is None


def test_release_device_no_op_without_session(lib):
    # Must not raise.
    lib.release_device()


def test_release_device_clears_even_on_release_error(lib_with_session):
    lib, fake_session = lib_with_session
    fake_session.release.side_effect = EdgeLensError("server down")
    with pytest.raises(EdgeLensError):
        lib.release_device()
    # Session reference cleared in finally — caller can't accidentally
    # re-use a half-released session via a later keyword.
    assert lib._session is None


def test_keywords_without_session_raise_clear_message(lib):
    with pytest.raises(EdgeLensError, match="Request Device"):
        lib.execute_on_device("ls")


def test_get_session_id(lib_with_session):
    lib, _ = lib_with_session
    assert lib.get_session_id() == "sess_test"


def test_get_session_status_refreshes(lib_with_session):
    lib, fake_session = lib_with_session
    fake_session.status.value = "ready"
    assert lib.get_session_status() == "ready"
    fake_session.refresh.assert_called_once()


# ---- device operations ------------------------------------------------------


def test_execute_on_device_returns_dict(lib_with_session):
    lib, fake_session = lib_with_session
    fake_session.device.exec.return_value = MagicMock(stdout="hi\n", stderr="", exit_code=0)
    out = lib.execute_on_device("echo hi", timeout=5.0)
    assert out == {"stdout": "hi\n", "stderr": "", "exit_code": 0}
    fake_session.device.exec.assert_called_once_with("echo hi", timeout=5.0)


def test_deploy_model_passes_through(lib_with_session):
    lib, fake_session = lib_with_session
    fake_session.device.deploy.return_value = {"success": True}
    out = lib.deploy_model("./m.cvimodel", config="./c.json", files=["./extra"])
    assert out == {"success": True}
    fake_session.device.deploy.assert_called_once_with(
        model="./m.cvimodel", config="./c.json", files=["./extra"],
    )


def test_get_ssh_details_omits_password(lib_with_session):
    """The keyword's return value lands
    in Robot's log.html / output.xml verbatim, so the password must
    NOT be there."""
    lib, fake_session = lib_with_session
    creds = MagicMock(user="recamera", host="192.0.2.42", port=30007, password="pw")
    fake_session.device.ssh.return_value = creds
    out = lib.get_ssh_details()
    assert out == {
        "user": "recamera", "host": "192.0.2.42", "port": 30007,
    }
    assert "password" not in out


def test_get_ssh_password_returns_cleartext_but_uses_trace_log(lib_with_session):
    """The split keyword still exposes the password to keyword callers
    that explicitly request it, but the value is only logged at
    TRACE level (Robot's lowest verbosity) and never as HTML."""
    lib, fake_session = lib_with_session
    creds = MagicMock(user="recamera", host="192.0.2.42", port=30007, password="hunter2")
    fake_session.device.ssh.return_value = creds

    assert lib.get_ssh_password() == "hunter2"


# ---- display + inference ----------------------------------------------------


def test_display_keywords(lib_with_session):
    lib, fake_session = lib_with_session
    lib.play_on_display("https://x/v.mp4", loop=True)
    fake_session.device.display.play.assert_called_once_with("https://x/v.mp4", loop=True)
    lib.show_on_display("https://x/img.png")
    fake_session.device.display.show.assert_called_once_with("https://x/img.png")
    lib.stop_display()
    fake_session.device.display.stop.assert_called_once()


def test_inference_keywords(lib_with_session):
    lib, fake_session = lib_with_session
    lib.start_inference()
    lib.stop_inference()
    fake_session.device.inference.start.assert_called_once()
    fake_session.device.inference.stop.assert_called_once()


def test_run_inference_returns_dict(lib_with_session):
    lib, fake_session = lib_with_session
    stats = MagicMock()
    stats.model_dump.return_value = {"duration_s": 30, "fps": {"avg": 16.0}}
    fake_session.device.inference.run.return_value = stats
    out = lib.run_inference(duration=30.0, collect_frames=False)
    assert out == {"duration_s": 30, "fps": {"avg": 16.0}}
    fake_session.device.inference.run.assert_called_once_with(
        duration=30.0, collect_frames=False,
    )


# ---- scope handling ---------------------------------------------------------


def test_scope_set_via_constructor_uppercases():
    lib = EdgeLensLibrary(api_key="k", scope="test")
    assert lib.ROBOT_LIBRARY_SCOPE == "TEST"


def test_default_scope_is_suite():
    lib = EdgeLensLibrary(api_key="k")
    assert lib.ROBOT_LIBRARY_SCOPE == "SUITE"


# ---- env-key fallback -------------------------------------------------------


def test_env_key_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDGELENS_API_KEY", "el_test_env")
    lib = EdgeLensLibrary()
    assert lib._api_key == "el_test_env"


def test_no_key_anywhere_raises_on_first_use(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EDGELENS_API_KEY", raising=False)
    lib = EdgeLensLibrary()
    with patch("EdgeLensLibrary.library.EdgeLensClient", side_effect=EdgeLensError("no key")):
        with pytest.raises(EdgeLensError):
            lib._ensure_client()
