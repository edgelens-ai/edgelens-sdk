#!/bin/sh
# Build an sdist and a wheel for every Python package into /dist.
#
# Runs inside the Dockerfile.dist image. stdin is `git archive HEAD`, so the
# artifacts are built from the committed tree and nothing untracked (a local
# venv, a cache, a stray .env) can reach them.
#
# `python -m build` with no --sdist/--wheel builds the sdist first and then
# the wheel from the unpacked sdist, so a file the sdist forgets breaks the
# wheel build here instead of a user's install.
#
# --no-isolation builds with the hash-pinned hatchling in /opt/build (see
# Dockerfile.dist) instead of fetching one from PyPI; build still refuses
# when that hatchling does not satisfy a pyproject's build-system.requires.
# SOURCE_DATE_EPOCH (the commit time, set by `make dist`) fixes every
# timestamp in the archives, so a rebuild of the same commit is
# byte-identical.
set -eu

: "${SOURCE_DATE_EPOCH:?set SOURCE_DATE_EPOCH to the commit time}"
export SOURCE_DATE_EPOCH

PACKAGES="core/python integrations/cli integrations/mcp integrations/pytest integrations/robot"

src=$(mktemp -d)
tar -x -C "$src"

for pkg in $PACKAGES; do
    echo "=== python: $pkg"
    /opt/build/bin/python -m build --no-isolation --outdir /dist "$src/$pkg" >"$src/build.log" 2>&1 || {
        cat "$src/build.log"
        exit 1
    }
    grep -E '^Successfully built' "$src/build.log"
done
