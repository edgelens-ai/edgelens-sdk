"""Tests for registry.py: moving-tag selection and the registry reads."""

from __future__ import annotations

import json

import pytest

import registry
from registry import ABSENT, Registry, RegistryError, main, select_tags

IMAGE = "docker.io/edgelensai/edgelens-sdk"
CONFIG = "sha256:" + "c" * 64
V2 = "application/vnd.docker.distribution.manifest.v2+json"
OCI = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"


# ---- selection --------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "released", "want"),
    [
        # First release ever, and the newest release.
        ("0.2.2", [], ["0.2", "latest"]),
        ("0.2.3", ["0.2.2", "latest"], ["0.2", "latest"]),
        ("0.3.0", ["0.2.2", "0.2", "latest"], ["0.3", "latest"]),
        # A re-run of the newest release moves both again (to itself).
        ("0.2.2", ["0.2.2", "latest"], ["0.2", "latest"]),
        # An older tag published after a newer one moves nothing back.
        ("0.2.0", ["0.2.2", "0.2", "latest"], []),
        # A patch to an older line moves its own X.Y, never latest.
        ("0.1.5", ["0.1.4", "0.2.2"], ["0.1"]),
        ("0.2.3", ["0.2.2", "0.3.0"], ["0.2"]),
        # Numeric, not string, order: 0.10 is newer than 0.9.
        ("0.9.1", ["0.10.0"], ["0.9"]),
        ("0.10.0", ["0.9.9"], ["0.10", "latest"]),
        ("0.2.10", ["0.2.9"], ["0.2", "latest"]),
        ("0.2.9", ["0.2.10"], []),
        ("1.0.0", ["0.99.99"], ["1.0", "latest"]),
        # Tags that are not X.Y.Z are not releases.
        ("0.2.2", ["latest", "0.2", "0.3.0-rc1", "v9.9.9", "nightly"], ["0.2", "latest"]),
    ],
)
def test_select_tags(version, released, want):
    assert select_tags(version, released) == want


def test_select_tags_refuses_a_malformed_version():
    with pytest.raises(ValueError, match="not X.Y.Z"):
        select_tags("v0.2.2", [])


# ---- a fake registry -----------------------------------------------------------


def manifest(media=V2, config=CONFIG):
    body = {"schemaVersion": 2, "mediaType": media}
    if media in (V2, OCI):
        body["config"] = {"mediaType": "application/vnd.oci.image.config.v1+json", "size": 1, "digest": config}
    else:
        body["manifests"] = []
    return 200, {"content-type": media}, json.dumps(body).encode()


def not_found(code):
    return 404, {}, json.dumps({"errors": [{"code": code, "message": "x"}]}).encode()


class FakeRegistry:
    """Demands a bearer token, then serves tag pages and canned manifests."""

    def __init__(self, pages=(), manifests=None, token_status=200, list_status=200):
        self.pages = list(pages)
        self.manifests = manifests or {}
        self.token_status = token_status
        self.list_status = list_status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if url.startswith("https://auth.docker.io/token"):
            return self.token_status, {}, json.dumps({"token": "tok"}).encode()
        if headers.get("Authorization") != "Bearer tok":
            return 401, {
                "www-authenticate": 'Bearer realm="https://auth.docker.io/token",'
                'service="registry.docker.io",scope="repository:edgelensai/edgelens-sdk:pull"'
            }, b""
        if "/manifests/" in url:
            tag = url.rsplit("/", 1)[1]
            return self.manifests.get(tag, not_found("MANIFEST_UNKNOWN"))
        if self.list_status != 200:
            return self.list_status, {}, b'{"errors":[{"code":"DENIED"}]}'
        page = int(url.rsplit("last=p", 1)[1]) if "last=" in url else 0
        headers_out = {}
        if page + 1 < len(self.pages):
            headers_out["link"] = (
                f'</v2/edgelensai/edgelens-sdk/tags/list?n=1000&last=p{page + 1}>; rel="next"'
            )
        return 200, headers_out, json.dumps({"tags": self.pages[page]}).encode()


# ---- tag listing ----------------------------------------------------------------


def test_tags_authenticates_and_follows_pages():
    fake = FakeRegistry([["0.2.0", "0.2.1"], ["0.2.2", "latest"]])
    assert Registry(IMAGE, fake).tags() == ["0.2.0", "0.2.1", "0.2.2", "latest"]
    urls = [u for u, _ in fake.calls]
    assert urls[0] == "https://registry-1.docker.io/v2/edgelensai/edgelens-sdk/tags/list?n=1000"
    assert urls[1].startswith("https://auth.docker.io/token?")
    assert "scope=repository%3Aedgelensai%2Fedgelens-sdk%3Apull" in urls[1]
    assert urls[-1].endswith("last=p1")


def test_tags_fails_on_a_registry_error():
    with pytest.raises(RegistryError, match="HTTP 403"):
        Registry(IMAGE, FakeRegistry([["0.2.2"]], list_status=403)).tags()


def test_tags_fails_when_no_token_is_granted():
    with pytest.raises(RegistryError, match="token request returned HTTP 503"):
        Registry(IMAGE, FakeRegistry([["0.2.2"]], token_status=503)).tags()


def test_a_plain_http_token_realm_is_refused():
    def fetch(url, headers):
        return 401, {"www-authenticate": 'Bearer realm="http://auth.example/token"'}, b""

    with pytest.raises(RegistryError, match="not https"):
        Registry(IMAGE, fetch).tags()


@pytest.mark.parametrize(
    "image",
    ["edgelensai/edgelens-sdk", "docker.io/edgelensai/edgelens-sdk:0.2.4", "docker.io/x@sha256:00"],
)
def test_split_image_refuses_a_tag_digest_or_missing_host(image):
    with pytest.raises(ValueError):
        registry.split_image(image)


def test_split_image_maps_docker_hub():
    assert registry.split_image("docker.io/python") == ("registry-1.docker.io", "library/python")
    assert registry.split_image("ghcr.io/o/n") == ("ghcr.io", "o/n")


# ---- digest ----------------------------------------------------------------------


@pytest.mark.parametrize("media", [V2, OCI])
def test_config_digest_of_a_single_image(media):
    fake = FakeRegistry(manifests={"0.2.2": manifest(media)})
    assert Registry(IMAGE, fake).config_digest("0.2.2") == CONFIG
    url, headers = fake.calls[-1]
    assert url == "https://registry-1.docker.io/v2/edgelensai/edgelens-sdk/manifests/0.2.2"
    assert V2 in headers["Accept"] and OCI in headers["Accept"]


def test_only_manifest_unknown_means_absent(capsys):
    assert main(["digest", f"{IMAGE}:0.2.9"], FakeRegistry()) == ABSENT
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "answer",
    [
        not_found("NAME_UNKNOWN"),
        not_found("NOT_FOUND"),
        (404, {}, b"page not found"),
        (401, {}, b'{"errors":[{"code":"UNAUTHORIZED"}]}'),
        (403, {}, b'{"errors":[{"code":"DENIED"}]}'),
        (429, {}, b'{"errors":[{"code":"TOOMANYREQUESTS"}]}'),
        (500, {}, b""),
        manifest(OCI_INDEX),
        manifest(V2, config="sha256:short"),
        (200, {}, b"not json"),
    ],
    ids=[
        "name-unknown",
        "not-found-code",
        "plain-404",
        "unauthorized",
        "denied",
        "rate-limited",
        "server-error",
        "index",
        "bad-config-digest",
        "not-json",
    ],
)
def test_any_other_answer_is_an_error_not_absence(capsys, answer):
    fake = FakeRegistry(manifests={"0.2.2": answer})
    assert main(["digest", f"{IMAGE}:0.2.2"], fake) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("registry: ")


def test_a_network_failure_is_an_error():
    def fetch(url, headers):
        raise OSError("Name or service not known")

    assert main(["digest", f"{IMAGE}:0.2.2"], fetch) == 1


@pytest.mark.parametrize("ref", [IMAGE, f"{IMAGE}:", "localhost:5000/x"])
def test_digest_refuses_a_reference_without_a_tag(ref):
    assert main(["digest", ref], FakeRegistry()) == 1


# ---- command line -----------------------------------------------------------------


def test_moving_tags_prints_the_tags_to_move(capsys):
    assert main(["moving-tags", IMAGE, "0.2.3"], FakeRegistry([["0.2.2", "latest"]])) == 0
    assert capsys.readouterr().out == "0.2 latest\n"


def test_moving_tags_prints_nothing_for_an_older_version(capsys):
    assert main(["moving-tags", IMAGE, "0.2.0"], FakeRegistry([["0.2.2", "latest"]])) == 0
    assert capsys.readouterr().out == "\n"


def test_moving_tags_fails_closed_on_a_registry_error(capsys):
    assert main(["moving-tags", IMAGE, "0.2.3"], FakeRegistry([["0.2.2"]], list_status=500)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HTTP 500" in captured.err


def test_unknown_usage_exits_2():
    assert main(["push", IMAGE], FakeRegistry()) == 2
