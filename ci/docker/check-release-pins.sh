#!/usr/bin/env bash
# Release lint that refuses to publish a non-digest-pinned edgelensai/edgelens-sdk
# image.
#
# Run from CI on the tag-push job:
#   ./ci/docker/check-release-pins.sh ci/docker/Dockerfile ci/github-action/action.yml
set -euo pipefail

errors=0

DOCKERFILE="${1:-ci/docker/Dockerfile}"
ACTION_YML="${2:-ci/github-action/action.yml}"

if grep -q '^FROM .*<DIGEST>' "$DOCKERFILE"; then
    echo "::error::$DOCKERFILE has unresolved <DIGEST> placeholder"
    errors=$((errors+1))
fi
if grep -q 'TODO(release):' "$DOCKERFILE"; then
    echo "::warning::$DOCKERFILE still carries TODO(release) markers — confirm digest pinning landed"
fi
if grep -q 'REPLACE_AT_RELEASE_TIME' "$DOCKERFILE"; then
    echo "::error::$DOCKERFILE K6_SHA256 placeholder not replaced"
    errors=$((errors+1))
fi

# Refuse :latest in the action.yml default.
if grep -E 'default: "edgelensai/edgelens-sdk:latest"' "$ACTION_YML" >/dev/null; then
    echo "::error::$ACTION_YML default image is :latest — pin a version"
    errors=$((errors+1))
fi

if [ "$errors" -gt 0 ]; then
    exit 1
fi
echo "ok: release pins resolved"
