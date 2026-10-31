"""Check or set the one version every package and artifact in this repo carries.

Usage:
  version.py check ROOT [--files-from FILE]
  version.py set ROOT X.Y.Z [--files-from FILE]

ROOT/VERSION is the source. `check` exits 1, naming each file and the value
it holds, when any copy disagrees with it. `set` rewrites VERSION and every
copy it can edit as text; the two package-lock.json files are left to npm
(`make set-version` regenerates them, then runs the check).

--files-from names a file (or - for stdin) listing the paths, relative to
ROOT, that the docs scan reads; `make` passes `git ls-files`, so untracked
trees are never scanned. Without it every file under ROOT is read.

Derived rather than copied, so not listed here:
  - the five pyproject.toml versions (hatchling reads each package's
    __version__; the check only asserts the pyproject declares it dynamic);
  - the Python User-Agent (built from edgelens.__version__);
  - the Robot Framework library version (EdgeLensLibrary.__version__).

Also held to VERSION: the GitLab template's default EDGELENS_IMAGE, and the
tag (v<version>) that any GitLab remote include of the template names.

Standard library only (tomllib: Python 3.11+).
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

# pyproject.toml : the file hatchling reads __version__ from, relative to it.
# Core and robot keep it in _version.py because a submodule reads it while
# the package is still importing; the package __init__ re-exports it.
PY_PACKAGES = {
    "core/python/pyproject.toml": "edgelens/_version.py",
    "integrations/cli/pyproject.toml": "edgelens_cli/__init__.py",
    "integrations/mcp/pyproject.toml": "edgelens_mcp/__init__.py",
    "integrations/pytest/pyproject.toml": "pytest_edgelens/__init__.py",
    "integrations/robot/pyproject.toml": "EdgeLensLibrary/_version.py",
}
CORE_DEPENDENTS = [p for p in PY_PACKAGES if p.startswith("integrations/")]

NPM_PACKAGES = ["core/typescript/package.json", "integrations/playwright/package.json"]
NPM_CORE_RANGES = {
    "integrations/playwright/package.json": [("peerDependencies", "@edgelens/core")],
    "examples/playwright/package.json": [
        ("devDependencies", "@edgelens/core"),
        ("devDependencies", "@edgelens/playwright-plugin"),
    ],
}
LOCKS = {
    "core/typescript/package-lock.json": [],
    "integrations/playwright/package-lock.json": ["../../core/typescript"],
}

TS_USER_AGENT = "core/typescript/src/http.ts"
ACTION_YML = "ci/github-action/action.yml"
GITLAB_TEMPLATE = "ci/gitlab/edgelens.gitlab-ci.yml"
IMAGE = "edgelensai/edgelens-sdk"

PY_VERSION = re.compile(r'^(__version__ = ")([^"]*)(")', re.M)
CORE_RANGE = re.compile(r'("edgelens-sdk)([^"]*)(")')
TS_UA = re.compile(r'("edgelens-typescript/)([^"]*)(")')
ACTION_DEFAULT = re.compile(r'(^    default: "' + re.escape(IMAGE) + r':)([^"]*)(")', re.M)
# The GitLab template's default image: the release's own tag, never :latest.
GITLAB_DEFAULT = re.compile(r'(^    EDGELENS_IMAGE: "' + re.escape(IMAGE) + r':)([^"]*)(")', re.M)
# In any tracked text file: the action's ref, a pinned image tag, and the
# ref a GitLab remote include fetches the template from (a branch such as
# main fails the check, being a moving ref).
DOC_PATTERNS = [
    ("github-action ref", re.compile(r"(github-action@)([\w.\-]+)()"), "v{v}"),
    ("image tag", re.compile(r"(" + re.escape(IMAGE) + r":)(\d+\.\d+\.\d+)()"), "{v}"),
    (
        "gitlab include ref",
        re.compile(r"(raw\.githubusercontent\.com/edgelens-ai/edgelens-sdk/)([^/\s\"']+)(/ci/gitlab/)"),
        "v{v}",
    ),
]
SKIP_DIRS = {".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__"}

problems: list[str] = []


def bad(path: str, what: str, found: object, want: str) -> None:
    problems.append(f"{path}: {what} is {found!r}, VERSION says {want!r}")


def core_range(v: str) -> str:
    major, minor, _ = v.split(".")
    return f">={v},<{major}.{int(minor) + 1}"


def doc_files(root: Path, files_from: str | None) -> list[str]:
    if files_from is None:
        return sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts)
        )
    text = sys.stdin.read() if files_from == "-" else Path(files_from).read_text()
    return [line for line in text.splitlines() if line]


def read_text(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None


def check(root: Path, docs: list[str]) -> int:
    v = (root / "VERSION").read_text().strip()
    if not SEMVER.match(v):
        print(f"FAIL VERSION: {v!r} is not X.Y.Z")
        return 1

    for pyproject, init in PY_PACKAGES.items():
        data = tomllib.loads((root / pyproject).read_text())
        project = data.get("project", {})
        if "version" in project:
            bad(pyproject, "project.version (should be dynamic)", project["version"], v)
        if "version" not in project.get("dynamic", []):
            problems.append(f"{pyproject}: version is not listed in project.dynamic")
        path = data.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
        if path != init:
            problems.append(f"{pyproject}: tool.hatch.version.path is {path!r}, want {init!r}")
        init_rel = str(Path(pyproject).parent / init)
        m = PY_VERSION.search((root / init_rel).read_text())
        if not m or m.group(2) != v:
            bad(init_rel, "__version__", m and m.group(2), v)

    for pyproject in CORE_DEPENDENTS:
        ranges = [m.group(2) for m in CORE_RANGE.finditer((root / pyproject).read_text())]
        if ranges != [core_range(v)]:
            bad(pyproject, "edgelens-sdk range", ranges, core_range(v))

    for pkg in NPM_PACKAGES:
        found = json.loads((root / pkg).read_text()).get("version")
        if found != v:
            bad(pkg, "version", found, v)
    for pkg, deps in NPM_CORE_RANGES.items():
        manifest = json.loads((root / pkg).read_text())
        for section, name in deps:
            found = manifest.get(section, {}).get(name)
            if found != f"^{v}":
                bad(pkg, f"{section}.{name}", found, f"^{v}")

    for lock, linked in LOCKS.items():
        data = json.loads((root / lock).read_text())
        packages = data.get("packages", {})
        own = Path(lock).parent / "package.json"
        manifest = json.loads((root / own).read_text())
        for key, found in [
            ("version", data.get("version")),
            ('packages[""].version', packages.get("", {}).get("version")),
            *[(f'packages["{p}"].version', packages.get(p, {}).get("version")) for p in linked],
        ]:
            if found != v:
                bad(lock, key, found, v)
        for section in ("dependencies", "peerDependencies", "devDependencies"):
            if packages.get("", {}).get(section, {}) != manifest.get(section, {}):
                problems.append(f'{lock}: packages[""].{section} differs from {own}; regenerate it')

    m = TS_UA.search((root / TS_USER_AGENT).read_text())
    if not m or m.group(2) != v:
        bad(TS_USER_AGENT, "User-Agent version", m and m.group(2), v)

    m = ACTION_DEFAULT.search((root / ACTION_YML).read_text())
    if not m or m.group(2) != v:
        bad(ACTION_YML, f"image default ({IMAGE}:...)", m and m.group(2), v)

    m = GITLAB_DEFAULT.search((root / GITLAB_TEMPLATE).read_text())
    if not m or m.group(2) != v:
        bad(GITLAB_TEMPLATE, f"EDGELENS_IMAGE default ({IMAGE}:...)", m and m.group(2), v)

    for rel in docs:
        text = read_text(root, rel)
        if text is None:
            continue
        for what, pattern, want in DOC_PATTERNS:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                if m.group(2) != want.format(v=v):
                    bad(f"{rel}:{line}", what, m.group(2), want.format(v=v))

    for p in problems:
        print(f"FAIL {p}")
    if problems:
        print(f"version-check: {len(problems)} mismatches against VERSION {v}")
        return 1
    print(f"version-check: every copy agrees with VERSION {v}")
    return 0


def rewrite(root: Path, rel: str, pattern: re.Pattern[str], value: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    new = pattern.sub(lambda m: m.group(1) + value + m.group(3), text)
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"set  {rel}")


def set_json(root: Path, rel: str, keys: list[tuple[str, ...]], value: str) -> None:
    # Edits the text in place, so the file's own formatting is kept.
    path = root / rel
    text = path.read_text()
    data = json.loads(text)
    for key in keys:
        node = data
        for part in key[:-1]:
            node = node[part]
        old = node[key[-1]]
        pattern = re.compile(r'("' + re.escape(key[-1]) + r'":\s*")' + re.escape(old) + r'(")')
        text, n = pattern.subn(lambda m: m.group(1) + value + m.group(2), text, count=1)
        if n != 1:
            sys.exit(f"{rel}: cannot find {'.'.join(key)}")
    path.write_text(text)
    print(f"set  {rel}")


def set_version(root: Path, v: str, docs: list[str]) -> None:
    if not SEMVER.match(v):
        sys.exit(f"{v!r} is not X.Y.Z")
    (root / "VERSION").write_text(v + "\n")
    print("set  VERSION")
    for pyproject, init in PY_PACKAGES.items():
        rewrite(root, str(Path(pyproject).parent / init), PY_VERSION, v)
    for pyproject in CORE_DEPENDENTS:
        rewrite(root, pyproject, CORE_RANGE, core_range(v))
    for pkg in NPM_PACKAGES:
        set_json(root, pkg, [("version",)], v)
    for pkg, deps in NPM_CORE_RANGES.items():
        set_json(root, pkg, deps, f"^{v}")
    rewrite(root, TS_USER_AGENT, TS_UA, v)
    rewrite(root, ACTION_YML, ACTION_DEFAULT, v)
    rewrite(root, GITLAB_TEMPLATE, GITLAB_DEFAULT, v)
    for rel in docs:
        if read_text(root, rel) is None:
            continue
        for _, pattern, want in DOC_PATTERNS:
            rewrite(root, rel, pattern, want.format(v=v))


def main(argv: list[str]) -> int:
    files_from = None
    if "--files-from" in argv:
        i = argv.index("--files-from")
        files_from = argv[i + 1]
        del argv[i : i + 2]
    if len(argv) == 2 and argv[0] == "check":
        root = Path(argv[1])
        return check(root, doc_files(root, files_from))
    if len(argv) == 3 and argv[0] == "set":
        root = Path(argv[1])
        set_version(root, argv[2], doc_files(root, files_from))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
