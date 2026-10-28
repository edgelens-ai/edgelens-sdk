#!/bin/sh
# Release lint that refuses to publish a non-digest-pinned edgelensai/edgelens-sdk
# image: every FROM line must carry @sha256:<64 hex>, and the k6 checksum
# must be a real value.
#
# Run from CI on the tag-push job:
#   ./ci/docker/check-release-pins.sh ci/docker/Dockerfile ci/github-action/action.yml
#
# A missing or empty action file skips the action.yml check; the Dockerfile
# is required.
set -eu

errors=0

DOCKERFILE="${1:-ci/docker/Dockerfile}"
ACTION_YML="${2:-ci/github-action/action.yml}"

if [ ! -s "$DOCKERFILE" ]; then
    echo "::error::$DOCKERFILE is missing or empty"
    exit 1
fi

unpinned=$(grep -nE '^[[:space:]]*FROM[[:space:]]' "$DOCKERFILE" \
    | grep -vE '^[0-9]+:[[:space:]]*FROM[[:space:]]+(--[^[:space:]]+[[:space:]]+)*[^[:space:]]+@sha256:[0-9a-f]{64}([[:space:]]|$)' \
    || true)
if [ -n "$unpinned" ]; then
    echo "$unpinned" | while IFS= read -r line; do
        echo "::error::$DOCKERFILE FROM line not pinned by @sha256 digest: $line"
    done
    errors=$((errors+1))
fi
if grep -q 'TODO(release):' "$DOCKERFILE"; then
    echo "::warning::$DOCKERFILE still carries TODO(release) markers — confirm digest pinning landed"
fi
if grep -q 'REPLACE_AT_RELEASE_TIME' "$DOCKERFILE"; then
    echo "::error::$DOCKERFILE K6_SHA256 placeholder not replaced"
    errors=$((errors+1))
fi
if ! grep -qE '^ARG K6_SHA256=[0-9a-f]{64}$' "$DOCKERFILE"; then
    echo "::error::$DOCKERFILE K6_SHA256 is not a 64-hex sha256"
    errors=$((errors+1))
fi

# Refuse :latest in the action.yml default.
if [ -s "$ACTION_YML" ] \
    && grep -E 'default: "edgelensai/edgelens-sdk:latest"' "$ACTION_YML" >/dev/null; then
    echo "::error::$ACTION_YML default image is :latest — pin a version"
    errors=$((errors+1))
fi

if [ "$errors" -gt 0 ]; then
    exit 1
fi
echo "ok: release pins resolved"
