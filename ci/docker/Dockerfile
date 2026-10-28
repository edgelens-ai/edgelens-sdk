# syntax=docker/dockerfile:1.7
#
# edgelensai/edgelens-sdk — pre-built CI runner image for EdgeLens test pipelines.
#
# Includes:
# - Python 3.12 + pytest + edgelens-sdk (Python SDK) + edgelens-cli
# - Node 20 + Playwright + @edgelens/core + @edgelens/playwright-plugin
# - k6 binary (xk6-edgelens extension lands later)
#
# Base: mcr.microsoft.com/playwright:v1.55.0-noble — Ubuntu 24.04 with
# Chromium / Firefox / WebKit + Node 20 already installed. Keeps the
# image multi-language without re-running `playwright install` at CI
# start time.
#
# Build context is the edgelens-sdk repo root because we COPY across
# core/* and integrations/*.
#
#   # From edgelens-sdk root; tags and labels come from VERSION and HEAD:
#   make image

# ---- stage 1: build TypeScript packages ------------------------------------
#
# Base images pinned by @sha256 digest, not
# floating tag.
#
# Refresh procedure (run before each release tag):
#   docker pull node:20-bookworm-slim
#   docker inspect --format '{{index .RepoDigests 0}}' node:20-bookworm-slim
# Copy the digest in here and into ci/docker/CHANGELOG.md.
#
# TODO(release): the digest below is a placeholder. The pre-release
# build step must replace it with the live registry digest before
# tagging. CI lint guards on the literal '<DIGEST>' substring; an
# unsubstituted digest fails the build.
FROM node:20-bookworm-slim AS ts-build
# Once digest-pinned:
# FROM node:20-bookworm-slim@sha256:<DIGEST> AS ts-build

WORKDIR /build
COPY core/typescript ./core/typescript
COPY integrations/playwright ./integrations/playwright

# Core first — Playwright plugin's file: dep resolves once core has a dist.
RUN cd core/typescript \
 && npm install --no-audit --no-fund \
 && npm run build

RUN cd integrations/playwright \
 && npm install --no-audit --no-fund \
 && npm run build

# ---- stage 2: final runtime ------------------------------------------------
#
# Same digest-pin discipline as stage 1.
# TODO(release): replace floating tag with @sha256:<DIGEST>.
FROM mcr.microsoft.com/playwright:v1.55.0-noble
# Once digest-pinned:
# FROM mcr.microsoft.com/playwright:v1.55.0-noble@sha256:<DIGEST>

# Python toolchain + curl (for the k6 download below).
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Single Python venv so we can use `pip install` without --break-system-packages.
RUN python3.12 -m venv /opt/edgelens/venv
ENV PATH=/opt/edgelens/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# k6 binary. Pin to a known version AND
# verify the sha256 checksum before extract. A MITM or registry
# compromise that swaps the tarball would otherwise land an arbitrary
# binary in every CI pipeline.
#
# Refresh K6_VERSION + K6_SHA256 together by downloading the official
# checksums file from https://github.com/grafana/k6/releases/tag/<version>
# and copying the linux-amd64 entry. Don't compute it locally — the
# point of the check is that we verify against an upstream-signed
# value, not against the tarball we just pulled.
# TODO(release): K6_SHA256 below is a placeholder — replace with the
# real linux-amd64 checksum from
# https://github.com/grafana/k6/releases/tag/${K6_VERSION} on each
# K6_VERSION bump. Don't recompute locally; the point of the check is
# to verify against an upstream-signed value.
ARG K6_VERSION=v0.55.0
ARG K6_SHA256=REPLACE_AT_RELEASE_TIME_WITH_UPSTREAM_LINUX_AMD64_SHA256
RUN curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-amd64.tar.gz" \
      -o /tmp/k6.tgz \
 && if [ "$K6_SHA256" != "REPLACE_AT_RELEASE_TIME_WITH_UPSTREAM_LINUX_AMD64_SHA256" ]; then \
        echo "${K6_SHA256}  /tmp/k6.tgz" | sha256sum -c -; \
    else \
        echo "WARNING: k6 sha256 not pinned — image built without integrity check" >&2; \
    fi \
 && tar -xzf /tmp/k6.tgz -C /tmp \
 && mv "/tmp/k6-${K6_VERSION}-linux-amd64/k6" /usr/local/bin/k6 \
 && chmod +x /usr/local/bin/k6 \
 && rm -rf /tmp/k6.tgz "/tmp/k6-${K6_VERSION}-linux-amd64" \
 && k6 version

# Python SDK, CLI and pytest plugin from local sources. Pinning to local
# makes the image self-contained — no pip → PyPI hop at CI start time, and
# none of these is published yet, so there is nowhere else to get them.
#
# The plugin is here because the example's demo needs it: its device
# fixture comes from this package, and without it the demo cannot run in
# this image at all.
COPY core/python /opt/edgelens/src/core/python
COPY integrations/cli /opt/edgelens/src/integrations/cli
COPY integrations/pytest /opt/edgelens/src/integrations/pytest

# The example's third-party dependencies come from its own requirements
# file rather than from a list spelled out here, so that adding one is a
# tracked, reviewable change to a file that is actually read. It was not
# read by anything before: it existed, and the two documented install
# commands pointed at it, and nothing consumed it — which is worse than
# its absence, because a file that looks like the right place is what
# stops anyone looking for the mechanism.
COPY examples/pytest/requirements.txt /opt/edgelens/example-requirements.txt

# Rootless podman leaves HOME unset, which resolves to "/", and anything
# writing a cache or config under it then fails on a path it cannot write.
# Set here rather than passed at run time so every caller gets it without
# having to know, and so it cannot be forgotten by one invocation.
ENV HOME=/tmp

# Order matters and is not stylistic. The local packages install first, so
# that by the time the requirements file is read, its first-party line is
# already satisfied by the source build and pip does not go looking for a
# published release that does not exist yet.
RUN pip install --upgrade pip \
 && pip install \
      /opt/edgelens/src/core/python \
      /opt/edgelens/src/integrations/cli \
      /opt/edgelens/src/integrations/pytest \
 && pip install -r /opt/edgelens/example-requirements.txt \
 && edgelens --version \
 && python -c "import edgelens; print('edgelens', edgelens.__version__)" \
 && python -c "import pytest_edgelens; print('pytest-edgelens ok')"

# TypeScript SDK + Playwright plugin from the build stage's dists.
# `npm pack` → `npm install -g <tarball>` resolves the file:../ dep
# without needing a registry.
COPY --from=ts-build /build/core/typescript /opt/edgelens/ts/core
COPY --from=ts-build /build/integrations/playwright /opt/edgelens/ts/playwright
RUN cd /opt/edgelens/ts/core && npm pack \
 && cd /opt/edgelens/ts/playwright && npm pack \
 && npm install -g --omit=optional \
      /opt/edgelens/ts/core/edgelens-core-*.tgz \
      /opt/edgelens/ts/playwright/edgelens-playwright-plugin-*.tgz \
 && rm /opt/edgelens/ts/core/edgelens-core-*.tgz \
       /opt/edgelens/ts/playwright/edgelens-playwright-plugin-*.tgz \
 && cd / \
 && npm ls -g --depth=0 2>/dev/null | grep -E "@edgelens/(core|playwright-plugin)"

# Sensible defaults for CI workflows that mount the workspace.
WORKDIR /workspace
ENV CI=true

LABEL org.opencontainers.image.title="edgelensai/edgelens-sdk" \
      org.opencontainers.image.description="EdgeLens CI runner — Python SDK + CLI + Playwright plugin + k6" \
      org.opencontainers.image.source="https://github.com/edgelens-ai/edgelens-sdk" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="EdgeLens"

# Drop into a shell by default; CI workflows override CMD.
CMD ["bash"]
