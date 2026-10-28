"""SSH passwords stay out of the models' repr() and str()."""

from __future__ import annotations

from edgelens.types import DeviceConnection, OSType, SSHCredentials

PASSWORD = "s3cret-Pa55word"


def test_ssh_credentials_repr_and_str_hide_password():
    creds = SSHCredentials(user="root", host="10.0.0.5", port=2222, password=PASSWORD)
    assert PASSWORD not in repr(creds)
    assert PASSWORD not in str(creds)
    assert "host='10.0.0.5'" in repr(creds)
    assert creds.password == PASSWORD
    assert creds.model_dump()["password"] == PASSWORD


def test_device_connection_repr_and_str_hide_password():
    conn = DeviceConnection(
        mac="aa:bb:cc:dd:ee:ff", host="10.0.0.5", ssh_user="root",
        ssh_password=PASSWORD, os=OSType.STOCK,
    )
    assert PASSWORD not in repr(conn)
    assert PASSWORD not in str(conn)
    assert conn.ssh_password == PASSWORD
    assert conn.model_dump()["ssh_password"] == PASSWORD


def test_password_repr_hidden_in_failed_assertion_message():
    creds = SSHCredentials(user="root", host="h", password=PASSWORD)
    try:
        assert creds.port == 2222, creds
    except AssertionError as e:
        assert PASSWORD not in str(e)
    else:
        raise AssertionError("expected the assertion to fail")
