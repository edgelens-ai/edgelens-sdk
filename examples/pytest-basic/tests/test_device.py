"""Allocate a device, run a command on it, and read its info.

The ``device`` fixture comes from the edgelens-pytest plugin. It is
session-scoped by default, so both tests share one allocated device,
which is released when the run ends.
"""


def test_run_command(device):
    result = device.exec("uname -a")
    assert result.success, result.stderr
    assert result.stdout.strip()


def test_device_info(device):
    info = device.info()
    assert info.hostname
    assert device.mac
