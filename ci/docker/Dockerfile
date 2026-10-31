# edgelensai/edgelens-sdk — pre-built CI runner image for EdgeLens test pipelines.
#
# Includes:
# - Python 3.12 + pytest + edgelens-sdk + edgelens-cli + edgelens-pytest
# - Node 22 + Playwright + @edgelens/core + @edgelens/playwright-plugin
# - k6 binary
#
# Base: mcr.microsoft.com/playwright:v1.55.0-noble — Ubuntu 24.04 with
# Chromium / Firefox / WebKit + Node 22 already installed. Keeps the
# image multi-language without re-running `playwright install` at CI
# start time.
#
# The SDK packages are the wheels and npm tarballs `make dist` built, the
# same files the release publishes to PyPI and npm. `make image` checks
# them against dist/SHA256SUMS and the commit in dist/BUILD_INFO, then
# places them in the build context's dist/ directory, from which they are
# bind-mounted for the install steps only. No sources, tests or build
# dependencies reach the image.
#
#   # From edgelens-sdk root, after `make dist`; the tag and labels come
#   # from VERSION and HEAD:
#   make image
#
# There is no `# syntax=` line: the builder's own Dockerfile frontend
# builds this file (podman/buildah, and BuildKit's built-in frontend under
# docker), so no frontend image is fetched at build time.
#
# Base images are pinned by the @sha256 digest of the multi-arch index,
# not by floating tag. Keep the tag in front of the digest so the line
# still says which release it is.
#
# Refresh procedure (every FROM line, before each release): take the
# index digest for the tag, for example
#   skopeo inspect --raw docker://<image>:<tag> | sha256sum
# or the Docker-Content-Digest header the registry returns for the tag's
# manifest.

FROM mcr.microsoft.com/playwright:v1.55.0-noble@sha256:b27e719ecbfef153e13fd24e8341736733bf2658b229677eb21ff57ff5d7fb29

# Python toolchain + curl (for the k6 download below).
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv \
    curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Single Python venv so we can use `pip install` without --break-system-packages.
RUN python3.12 -m venv /opt/edgelens/venv
ENV PATH=/opt/edgelens/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# k6 binary, pinned by version and verified against the upstream sha256
# before extract. A swapped tarball fails the build.
#
# Refresh procedure: bump K6_VERSION and K6_SHA256 together. Take the
# k6-<version>-linux-amd64.tar.gz line from the checksums file published
# with the release,
#   https://github.com/grafana/k6/releases/download/<version>/k6-<version>-checksums.txt
# never from a hash computed over a local download: the check verifies
# against upstream, not against the tarball just pulled. K6_VERSION
# follows the go.k6.io/k6 version in integrations/k6/go.mod.
ARG K6_VERSION=v0.55.0
ARG K6_SHA256=47a43a8dbb4c1f5d5bd7b8ed6a1b8c83b35546acf989b78400b4e6ce3adaf628
RUN curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-amd64.tar.gz" \
      -o /tmp/k6.tgz \
 && echo "${K6_SHA256}  /tmp/k6.tgz" | sha256sum -c - \
 && tar -xzf /tmp/k6.tgz -C /tmp \
 && mv "/tmp/k6-${K6_VERSION}-linux-amd64/k6" /usr/local/bin/k6 \
 && chmod +x /usr/local/bin/k6 \
 && rm -rf /tmp/k6.tgz "/tmp/k6-${K6_VERSION}-linux-amd64" \
 && k6 version

# Python SDK, CLI and pytest plugin from the dist/ wheels; their
# third-party dependencies come from PyPI.
RUN --mount=type=bind,source=dist,target=/dist \
    pip install /dist/edgelens_sdk-*.whl /dist/edgelens_cli-*.whl /dist/edgelens_pytest-*.whl \
 && edgelens --version \
 && python -c "import edgelens; print('edgelens', edgelens.__version__)" \
 && python -c "import pytest_edgelens; print('edgelens-pytest ok')"

# TypeScript SDK and Playwright plugin from the dist/ tarballs, installed
# globally. @playwright/test is the plugin's peer dependency; it is pinned
# to the base image's Playwright version so the browsers already in the
# image match it. The npm cache and logs go in the same layer.
ARG PLAYWRIGHT_VERSION=1.55.0
RUN --mount=type=bind,source=dist,target=/dist \
    npm install -g --omit=optional --no-audit --no-fund \
      /dist/edgelens-core-*.tgz \
      /dist/edgelens-playwright-plugin-*.tgz \
      "@playwright/test@${PLAYWRIGHT_VERSION}" \
 && npm ls -g --depth=0 2>/dev/null | grep -E "@edgelens/(core|playwright-plugin)|@playwright/test" \
 && npm cache clean --force \
 && rm -rf /root/.npm

# Sensible defaults for CI workflows that mount the workspace.
WORKDIR /workspace
ENV CI=true

LABEL org.opencontainers.image.title="edgelensai/edgelens-sdk" \
      org.opencontainers.image.description="EdgeLens CI runner — Python SDK + CLI + pytest plugin + Playwright plugin + k6" \
      org.opencontainers.image.source="https://github.com/edgelens-ai/edgelens-sdk" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="EdgeLens"

# Drop into a shell by default; CI workflows override CMD.
CMD ["bash"]
