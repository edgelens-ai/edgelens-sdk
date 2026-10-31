"""session_id encoded into URL paths.
Device.deploy honors allowed_root (sync + async).
device.upload() is removed — the platform has no /upload route.
"""

from __future__ import annotations

import asyncio

import pytest

from edgelens._http import encode_path_param
from edgelens.errors import DeviceError
from edgelens.types import DeviceConnection, OSType


def _conn() -> DeviceConnection:
    return DeviceConnection(
        mac="aa:bb:cc:00:00:01",
        host="192.0.2.42",
        ssh_user="recamera",
        ssh_password="x" * 24,
        os=OSType.RECAMAGINED,
    )


def test_encode_path_param_basic():
    assert encode_path_param("sess_abc123") == "sess_abc123"


def test_encode_path_param_escapes_slashes():
    """Slashes are encoded so a crafted value can't escape the path."""
    out = encode_path_param("../accounts/me/keys/shadow")
    assert "/" not in out
    assert "%2F" in out


def test_encode_path_param_escapes_special_chars():
    """Spaces, ?, &, # — anything URL-special — gets encoded."""
    for c in (" ", "?", "&", "#"):
        encoded = encode_path_param(f"sess_{c}suffix")
        assert c not in encoded


@pytest.mark.parametrize("value", ["", ".", ".."])
def test_encode_path_param_refuses_dot_segments(value):
    """A dot segment is resolved by the URL parser, encoded or not."""
    from edgelens.errors import EdgeLensError

    with pytest.raises(EdgeLensError):
        encode_path_param(value)


# ---- allowed_root --------------------------------------------------


def test_safe_open_passes_through_when_root_not_set(tmp_path):
    """Without allowed_root set, behavior is identical to open."""
    from edgelens.device import _safe_open

    f = tmp_path / "x.bin"
    f.write_bytes(b"contents")
    with _safe_open(f, allowed_root=None) as fh:
        assert fh.read() == b"contents"


def test_safe_open_accepts_path_inside_root(tmp_path):
    from edgelens.device import _safe_open

    root = tmp_path / "models"
    root.mkdir()
    target = root / "model.bin"
    target.write_bytes(b"m")
    with _safe_open(target, allowed_root=root) as fh:
        assert fh.read() == b"m"


def test_safe_open_rejects_path_outside_root(tmp_path):
    """Customer test code that uses a path traversal pattern is
    refused — no arbitrary read out of the allowed root."""
    from edgelens.device import _safe_open

    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"hunter2")
    with pytest.raises(DeviceError, match="allowed_upload_root"):
        _safe_open(outside, allowed_root=root)


def test_safe_open_rejects_symlink_escape(tmp_path):
    """Symlinks that point outside the root are caught by .resolve()."""
    from edgelens.device import _safe_open

    root = tmp_path / "models"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"hunter2")
    link = root / "evil.bin"
    link.symlink_to(secret)
    with pytest.raises(DeviceError):
        _safe_open(link, allowed_root=root)


# ---- upload() removed + async deploy path-jail --------------------------


def test_device_upload_raises_not_supported():
    """The /upload route never existed on the API (404 by contract).
    upload() now fails clearly at the SDK boundary, pointing at deploy()."""
    from edgelens.device import Device

    dev = Device(http=None, session_id="sess_x", connection=_conn())
    with pytest.raises(DeviceError, match="not supported"):
        dev.upload("./whatever", "/tmp/x")


def test_async_device_upload_raises_not_supported():
    from edgelens.aio import AsyncDevice

    dev = AsyncDevice(http=None, session_id="sess_x", connection=_conn())
    with pytest.raises(DeviceError, match="not supported"):
        asyncio.run(dev.upload("./whatever", "/tmp/x"))


def test_async_deploy_honors_allowed_root(tmp_path):
    """The async deploy enforces the same path-jail as the sync client:
    every input is opened through _safe_open, never a bare open()."""
    from edgelens.aio import AsyncDevice

    root = tmp_path / "models"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"hunter2")
    dev = AsyncDevice(http=None, session_id="sess_x", connection=_conn())
    dev._allowed_upload_root = root  # type: ignore[attr-defined]
    with pytest.raises(DeviceError, match="allowed_upload_root"):
        asyncio.run(dev.deploy(model=outside))
