"""Inspect every artifact in a dist directory before it may be published.

Usage: check-artifacts.py DIST_DIR REPO_DIR

Fails (exit 1) when:
  - an expected artifact is missing, or an unexpected one is present;
  - an artifact carries a path that must never ship: an audit or scratch
    tree, a .env file, node_modules, a virtualenv, or a tests/ directory;
  - an artifact's version differs from the repository's VERSION, or an npm
    manifest's @edgelens/core peer range is not ^VERSION;
  - an artifact lacks the LICENSE, or its LICENSE differs from the
    repository's;
  - an npm manifest still points at a local path (file:, link:, workspace:),
    lacks publishConfig.access=public, or names a main/module/types/exports
    target that is not in the tarball.

Standard library only, so it runs in any python image.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

PY_DISTS = {
    "edgelens_sdk": "core/python",
    "edgelens_cli": "integrations/cli",
    "edgelens_mcp": "integrations/mcp",
    "pytest_edgelens": "integrations/pytest",
    "robotframework_edgelens": "integrations/robot",
}
NPM_DISTS = {
    "edgelens-core": "core/typescript",
    "edgelens-playwright-plugin": "integrations/playwright",
}

FORBIDDEN = [
    (re.compile(r"(^|/)[^/]*audit[^/]*(/|$)"), "audit or review tree"),
    (re.compile(r"(^|/)\.env($|\.|/)"), ".env file"),
    (re.compile(r"(^|/)node_modules(/|$)"), "node_modules"),
    (re.compile(r"(^|/)\.?venv(/|$)"), "virtualenv"),
    (re.compile(r"(^|/)tests?(/|$)"), "tests/ directory"),
    (re.compile(r"(^|/)__pycache__(/|$)|\.py[co]$"), "bytecode"),
]

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)
    print(f"FAIL {msg}")


def scan_names(artifact: str, names: list[str]) -> None:
    for name in names:
        for pattern, what in FORBIDDEN:
            if pattern.search(name):
                fail(f"{artifact}: {what}: {name}")


def check_license(artifact: str, data: bytes | None, repo_license: bytes) -> None:
    if data is None:
        fail(f"{artifact}: no LICENSE")
    elif data != repo_license:
        fail(f"{artifact}: LICENSE differs from the repository LICENSE")


def check_wheel(path: Path, repo_license: bytes) -> None:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        scan_names(path.name, names)
        lic = [n for n in names if re.search(r"\.dist-info/licenses/LICENSE$", n)]
        check_license(path.name, zf.read(lic[0]) if lic else None, repo_license)


def check_sdist(path: Path, repo_license: bytes) -> None:
    with tarfile.open(path) as tf:
        names = tf.getnames()
        scan_names(path.name, names)
        top = names[0].split("/")[0]
        try:
            data = tf.extractfile(f"{top}/LICENSE").read()  # type: ignore[union-attr]
        except KeyError:
            data = None
        check_license(path.name, data, repo_license)


def manifest_targets(manifest: dict) -> list[str]:
    targets = [manifest[k] for k in ("main", "module", "types") if k in manifest]

    def walk(node: object) -> None:
        if isinstance(node, str):
            targets.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(manifest.get("exports", {}))
    return targets


def check_npm(path: Path, repo_license: bytes, version: str) -> None:
    with tarfile.open(path) as tf:
        names = tf.getnames()
        scan_names(path.name, names)
        try:
            data = tf.extractfile("package/LICENSE").read()  # type: ignore[union-attr]
        except KeyError:
            data = None
        check_license(path.name, data, repo_license)
        manifest = json.load(tf.extractfile("package/package.json"))  # type: ignore[arg-type]

    if manifest.get("version") != version:
        fail(f"{path.name}: manifest version {manifest.get('version')!r} is not {version}")
    peer = manifest.get("peerDependencies", {}).get("@edgelens/core")
    if peer is not None and peer != f"^{version}":
        fail(f"{path.name}: @edgelens/core peer range {peer!r} is not ^{version}")
    if manifest.get("publishConfig", {}).get("access") != "public":
        fail(f"{path.name}: publishConfig.access is not public")
    for section in ("dependencies", "peerDependencies", "optionalDependencies", "devDependencies"):
        for dep, spec in manifest.get(section, {}).items():
            if re.match(r"(file|link|workspace|portal):", spec):
                fail(f"{path.name}: {section}.{dep} is a local path: {spec}")
    members = {n.removeprefix("package/") for n in names}
    for target in manifest_targets(manifest):
        if target.removeprefix("./") not in members:
            fail(f"{path.name}: manifest points at {target}, not in the tarball")


def main() -> int:
    dist, repo = Path(sys.argv[1]), Path(sys.argv[2])
    repo_license = (repo / "LICENSE").read_bytes()
    version = (repo / "VERSION").read_text().strip()

    for pkg in [*PY_DISTS.values(), *NPM_DISTS.values()]:
        copy = repo / pkg / "LICENSE"
        if not copy.is_file() or copy.read_bytes() != repo_license:
            fail(f"{pkg}/LICENSE is missing or differs from the root LICENSE")

    seen: set[str] = set()
    for path in sorted(dist.iterdir()):
        name = path.name
        if name in ("BUILD_INFO", "SHA256SUMS"):
            continue
        if name.endswith(".whl"):
            stem, artifact_version = name.split("-")[:2]
            check_wheel(path, repo_license)
            kind = "wheel"
        elif name.endswith(".tar.gz"):
            stem, artifact_version = name[: -len(".tar.gz")].rsplit("-", 1)
            check_sdist(path, repo_license)
            kind = "sdist"
        elif name.endswith(".tgz"):
            stem, artifact_version = name[: -len(".tgz")].rsplit("-", 1)
            check_npm(path, repo_license, version)
            kind = "npm"
        else:
            fail(f"unexpected file in dist: {name}")
            continue
        if artifact_version != version:
            fail(f"{name}: version {artifact_version} is not VERSION {version}")
        seen.add(f"{kind}:{stem}")
        print(f"ok   {name}")

    expected = {f"{k}:{s}" for s in PY_DISTS for k in ("wheel", "sdist")}
    expected |= {f"npm:{s}" for s in NPM_DISTS}
    for missing in sorted(expected - seen):
        fail(f"missing artifact {missing}")
    for extra in sorted(seen - expected):
        fail(f"unexpected artifact {extra}")

    print(f"{len(seen)} artifacts at {version}, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
