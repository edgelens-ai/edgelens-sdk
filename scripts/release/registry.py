"""Read what a container registry holds for the CI image, over its HTTP API.

Usage:
  registry.py moving-tags IMAGE VERSION
  registry.py digest IMAGE:TAG

IMAGE is a repository reference with its registry host, such as
docker.io/edgelensai/edgelens-sdk. Reads are anonymous, so the repository
must be public. Standard library only, so it runs in any python image.

moving-tags prints, space-separated on one line (possibly empty), the
moving tags the release of VERSION should move. The released versions are
the X.Y.Z tags the registry lists, so the decision follows what has been
published, whatever order the releases ran in:

  - `X.Y` moves to VERSION only when no released X.Y.Z is higher;
  - `latest` moves to VERSION only when no released version is higher.

A lower version (a patch to an older line, or a re-run of an older tag)
therefore never moves either tag backwards. VERSION itself is not printed:
publish-image.sh always pushes it, unless the registry already holds that
exact image.

digest prints the config digest (sha256:...) the tag's manifest names. It
equals the local image ID of the same image under docker and podman,
whatever manifest format the push used. It exits 3 when, and only when,
the registry answers 404 with the error code MANIFEST_UNKNOWN: the tag
does not exist. Every other answer (auth, rate limit, network, a missing
repository, a multi-image index) exits 1, because it proves nothing
about the tag.

Any registry error fails moving-tags too (exit 1): an unknown tag list
proves nothing about what is newest.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

# Docker Hub serves the registry API from a different host than its name.
REGISTRY_HOSTS = {"docker.io": "registry-1.docker.io"}

SINGLE_MANIFESTS = {
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
}
INDEXES = {
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
}
MANIFEST_ACCEPT = ", ".join(sorted(SINGLE_MANIFESTS | INDEXES))

ABSENT = 3

Version = tuple[int, int, int]
# (url, headers) -> (status, response headers with lower-case names, body)
Fetch = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


class RegistryError(Exception):
    pass


class ManifestUnknown(Exception):
    pass


def parse_version(text: str) -> Version | None:
    m = SEMVER.match(text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def select_tags(version: str, released: Iterable[str]) -> list[str]:
    """The moving tags `version` should take, given the released tags."""
    own = parse_version(version)
    if own is None:
        raise ValueError(f"{version!r} is not X.Y.Z")
    versions = [v for v in map(parse_version, released) if v is not None]
    tags = []
    if all(v <= own for v in versions if v[:2] == own[:2]):
        tags.append(f"{own[0]}.{own[1]}")
    if all(v <= own for v in versions):
        tags.append("latest")
    return tags


def split_image(image: str) -> tuple[str, str]:
    """docker.io/org/name -> (registry API host, repository path)."""
    if "@" in image or ":" in image.rsplit("/", 1)[-1]:
        raise ValueError(f"{image!r} must name a repository, without a tag or digest")
    host, _, path = image.partition("/")
    if not path or ("." not in host and ":" not in host and host != "localhost"):
        raise ValueError(f"{image!r} must start with a registry host, e.g. docker.io/")
    if host == "docker.io" and "/" not in path:
        path = f"library/{path}"
    return REGISTRY_HOSTS.get(host, host), path


def split_ref(ref: str) -> tuple[str, str]:
    """docker.io/org/name:tag -> (docker.io/org/name, tag)."""
    image, sep, tag = ref.rpartition(":")
    if not sep or not tag or "/" in tag:
        raise ValueError(f"{ref!r} is not IMAGE:TAG")
    return image, tag


def parse_challenge(header: str) -> dict[str, str]:
    scheme, _, params = header.partition(" ")
    if scheme.lower() != "bearer":
        raise RegistryError(f"unsupported registry auth challenge: {header!r}")
    return dict(re.findall(r'(\w+)="([^"]*)"', params))


def next_link(headers: dict[str, str]) -> str | None:
    m = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", headers.get("link", ""))
    return m.group(1) if m else None


def error_codes(body: bytes) -> set[str]:
    try:
        errors = json.loads(body).get("errors") or []
    except (ValueError, AttributeError):
        return set()
    return {e.get("code") for e in errors if isinstance(e, dict)}


class Registry:
    """A registry API session for one repository, with an anonymous token."""

    def __init__(self, image: str, fetch: Fetch):
        self.image = image
        self.host, self.path = split_image(image)
        self.base = f"https://{self.host}"
        self.fetch = fetch
        self.auth: dict[str, str] = {}

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        headers = headers or {}
        status, resp_headers, body = self.fetch(url, {**headers, **self.auth})
        if status == 401 and not self.auth:
            self.auth = self.token(resp_headers.get("www-authenticate", ""))
            status, resp_headers, body = self.fetch(url, {**headers, **self.auth})
        return status, resp_headers, body

    def token(self, challenge_header: str) -> dict[str, str]:
        challenge = parse_challenge(challenge_header)
        realm = challenge.pop("realm", "")
        if not realm.startswith("https://"):
            raise RegistryError(f"registry token realm is not https: {realm!r}")
        challenge.setdefault("scope", f"repository:{self.path}:pull")
        status, _, body = self.fetch(f"{realm}?{urllib.parse.urlencode(challenge)}", {})
        if status != 200:
            raise RegistryError(f"registry token request returned HTTP {status}")
        grant = json.loads(body)
        token = grant.get("token") or grant.get("access_token")
        if not token:
            raise RegistryError("registry token response carries no token")
        return {"Authorization": f"Bearer {token}"}

    def tags(self) -> list[str]:
        """Every tag the registry lists for the repository, across pages."""
        url: str | None = f"{self.base}/v2/{self.path}/tags/list?n=1000"
        tags: list[str] = []
        while url:
            status, headers, body = self.get(url)
            if status != 200:
                raise RegistryError(f"tag list for {self.image} returned HTTP {status}: {body[:200]!r}")
            tags.extend(json.loads(body).get("tags") or [])
            link = next_link(headers)
            url = urllib.parse.urljoin(self.base, link) if link else None
        return tags

    def config_digest(self, tag: str) -> str:
        """The config digest of the single image `tag` names."""
        url = f"{self.base}/v2/{self.path}/manifests/{urllib.parse.quote(tag)}"
        status, headers, body = self.get(url, {"Accept": MANIFEST_ACCEPT})
        if status == 404 and "MANIFEST_UNKNOWN" in error_codes(body):
            raise ManifestUnknown(f"{self.image}:{tag}")
        if status != 200:
            raise RegistryError(f"manifest of {self.image}:{tag} returned HTTP {status}: {body[:200]!r}")
        manifest = json.loads(body)
        media = manifest.get("mediaType") or headers.get("content-type", "").split(";")[0]
        if media not in SINGLE_MANIFESTS:
            raise RegistryError(f"{self.image}:{tag} is a {media or 'untyped'} manifest, not a single image")
        digest = (manifest.get("config") or {}).get("digest", "")
        if not DIGEST.match(digest):
            raise RegistryError(f"{self.image}:{tag} manifest carries no config digest")
        return digest


def urllib_fetch(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def moving_tags(image: str, version: str, fetch: Fetch) -> int:
    released = Registry(image, fetch).tags()
    tags = select_tags(version, released)
    newest = max((v for v in map(parse_version, released) if v), default=None)
    shown = ".".join(map(str, newest)) if newest else "none"
    print(f"registry: {version} against released {shown}: moving {tags or 'nothing'}", file=sys.stderr)
    print(" ".join(tags))
    return 0


def digest(ref: str, fetch: Fetch) -> int:
    image, tag = split_ref(ref)
    try:
        print(Registry(image, fetch).config_digest(tag))
    except ManifestUnknown:
        print(f"registry: {ref} does not exist (manifest unknown)", file=sys.stderr)
        return ABSENT
    return 0


def main(argv: list[str], fetch: Fetch = urllib_fetch) -> int:
    try:
        if len(argv) == 3 and argv[0] == "moving-tags":
            return moving_tags(argv[1], argv[2], fetch)
        if len(argv) == 2 and argv[0] == "digest":
            return digest(argv[1], fetch)
    except (RegistryError, ValueError, OSError) as e:
        print(f"registry: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
