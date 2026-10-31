"""base_url validation + no plaintext api_key attribute.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgelens import EdgeLensClient
from edgelens.aio import AsyncEdgeLensClient
from edgelens.errors import AuthenticationError


# ---- scheme downgrade -------------------------------------------------


def test_http_scheme_refused_by_default():
    with pytest.raises(AuthenticationError, match="http://"):
        EdgeLensClient(api_key="k", base_url="http://api.edgelens.ai")


def test_http_scheme_allowed_when_explicitly_enabled():
    EdgeLensClient(
        api_key="k", base_url="http://api.edgelens.ai",
        allow_insecure_base_url=True,
    )


def test_local_http_dev_loop_needs_both_overrides(monkeypatch):
    """http://localhost is two relaxations: the scheme and the host."""
    with pytest.raises(AuthenticationError, match="private"):
        EdgeLensClient(
            api_key="k", base_url="http://localhost:8000",
            allow_insecure_base_url=True,
        )
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    EdgeLensClient(
        api_key="k", base_url="http://localhost:8000",
        allow_insecure_base_url=True,
    )


@pytest.mark.parametrize("url", [
    "http://169.254.169.254", "http://10.0.0.1", "http://[fd00:ec2::254]",
])
def test_insecure_flag_does_not_relax_host_check(url):
    """allow_insecure_base_url permits http:// only; it is not a
    private-host override."""
    with pytest.raises(AuthenticationError, match="private|reserved"):
        EdgeLensClient(api_key="k", base_url=url, allow_insecure_base_url=True)


def test_non_http_scheme_refused():
    for url in ("file:///etc/passwd", "gopher://evil", "javascript:alert(1)"):
        with pytest.raises(AuthenticationError, match="scheme"):
            EdgeLensClient(api_key="k", base_url=url)


def test_empty_base_url_refused():
    with pytest.raises(AuthenticationError):
        EdgeLensClient(api_key="k", base_url="")


# ---- private-IP refusal ----------------------------------------------


@pytest.mark.parametrize("host", [
    "127.0.0.1",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "169.254.169.254",  # cloud IMDS
    "0.0.0.0",
])
def test_private_ip_refused(host):
    with pytest.raises(AuthenticationError, match="private|reserved"):
        EdgeLensClient(api_key="k", base_url=f"https://{host}")


def test_ipv4_mapped_ipv6_imds_refused():
    """`https://[::ffff:169.254.169.254]/` must be rejected — the v6
    address's is_link_local is False, so the unwrap matters."""
    with pytest.raises(AuthenticationError, match="private|reserved"):
        EdgeLensClient(api_key="k", base_url="https://[::ffff:169.254.169.254]")


def test_public_https_accepted():
    """Sanity: real hosts still work."""
    EdgeLensClient(api_key="k", base_url="https://api.edgelens.ai")


# ---- private-address override -----------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5:8000", "192.168.1.10", "172.16.0.1"])
def test_private_ip_allowed_with_escape_hatch(host, monkeypatch):
    """EDGELENS_ALLOW_PRIVATE_BASE_URL=1 lets a base URL on a
    loopback/RFC1918 address through, for example a local test server."""
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    EdgeLensClient(api_key="k", base_url=f"https://{host}")


def test_private_ip_still_refused_without_escape_hatch(monkeypatch):
    """Default posture is unchanged: private IPs refused unless opted in."""
    monkeypatch.delenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", raising=False)
    with pytest.raises(AuthenticationError, match="private"):
        EdgeLensClient(api_key="k", base_url="https://10.0.0.5")


@pytest.mark.parametrize("host", ["169.254.169.254", "[::ffff:169.254.169.254]", "0.0.0.0"])
def test_escape_hatch_never_allows_imds_or_reserved(host, monkeypatch):
    """The hatch relaxes loopback + RFC1918 only. IMDS/link-local,
    unspecified, and reserved stay blocked even when it's set."""
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    with pytest.raises(AuthenticationError, match="link-local|reserved"):
        EdgeLensClient(api_key="k", base_url=f"https://{host}")


def test_escape_hatch_applies_to_async_client(monkeypatch):
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    AsyncEdgeLensClient(api_key="k", base_url="https://10.0.0.5:8000")


# ---- async sibling ---------------------------------------------------


def test_async_client_refuses_http_default():
    with pytest.raises(AuthenticationError, match="http://"):
        AsyncEdgeLensClient(api_key="k", base_url="http://api.edgelens.ai")


def test_async_client_allows_http_with_flag(monkeypatch):
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    AsyncEdgeLensClient(
        api_key="k", base_url="http://localhost:8000",
        allow_insecure_base_url=True,
    )


# ---- no plaintext api_key attribute ----------------------------------


def test_http_client_does_not_expose_api_key_attribute():
    """The raw api_key must not sit on the
    HTTPClient instance — only the Authorization header reference
    persists, and close() can wipe that."""
    c = EdgeLensClient(api_key="el_test_secret")
    assert not hasattr(c._http, "_api_key")
    # And the secret should not be on c._http itself either.
    assert "el_test_secret" not in str(vars(c._http))


# ---- follow_redirects=False -----------------------------------------------


def test_http_client_does_not_follow_redirects():
    """SSRF defense-in-depth: a 3xx from the platform must not cause
    the Bearer to be replayed to the redirect target."""
    c = EdgeLensClient(api_key="k")
    assert c._http._client.follow_redirects is False


def test_async_http_client_does_not_follow_redirects():
    c = AsyncEdgeLensClient(api_key="k")
    assert c._http._client.follow_redirects is False


# ---- shared host table -----------------------------------------------------
#
# core/testdata/base_url_hosts.json is also run by the TypeScript suite, so
# the two clients refuse exactly the same hosts.

_HOSTS = json.loads(
    (Path(__file__).resolve().parents[2] / "testdata" / "base_url_hosts.json").read_text()
)


@pytest.mark.parametrize("host", _HOSTS["refused"])
def test_shared_refused_hosts(host, monkeypatch):
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    with pytest.raises(AuthenticationError, match="link-local/reserved"):
        EdgeLensClient(api_key="k", base_url=f"https://{host}/")


@pytest.mark.parametrize("host", _HOSTS["private"])
def test_shared_private_hosts(host, monkeypatch):
    with pytest.raises(AuthenticationError, match="private/loopback"):
        EdgeLensClient(api_key="k", base_url=f"https://{host}/")
    monkeypatch.setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
    EdgeLensClient(api_key="k", base_url=f"https://{host}/")


@pytest.mark.parametrize("host", _HOSTS["public"])
def test_shared_public_hosts(host):
    EdgeLensClient(api_key="k", base_url=f"https://{host}/")
