#!/bin/sh
# Refuse to publish a dist/ that is missing or was not built from HEAD.
#
# Usage: check-fresh.sh DIST_DIR [TOKEN_VAR]
#
# `make dist` records the commit it archived in DIST_DIR/BUILD_INFO and a
# checksum of every artifact in DIST_DIR/SHA256SUMS. A new commit since then,
# an artifact changed or added by hand, or (when TOKEN_VAR is given) an unset
# token stops the upload. `make image` runs it without a token before it
# builds the image from DIST_DIR.
set -eu

dist=$1
token_var=${2:-}

if [ -n "$token_var" ]; then
    eval "token=\${$token_var:-}"
    if [ -z "$token" ]; then
        echo "refusing: $token_var is not set" >&2
        exit 1
    fi
fi

if [ ! -f "$dist/BUILD_INFO" ] || [ ! -f "$dist/SHA256SUMS" ]; then
    echo "refusing: $dist is missing or incomplete; run 'make dist' first" >&2
    exit 1
fi

built=$(sed -n 's/^commit=//p' "$dist/BUILD_INFO")
head=$(git rev-parse HEAD)
if [ "$built" != "$head" ]; then
    echo "refusing: $dist was built from $built but HEAD is $head; run 'make dist'" >&2
    exit 1
fi

listed=$(sed 's/^[0-9a-f]*  //' "$dist/SHA256SUMS" | sort)
present=$(cd "$dist" && ls | grep -vxE 'BUILD_INFO|SHA256SUMS' | sort)
if [ "$listed" != "$present" ]; then
    echo "refusing: $dist holds files that 'make dist' did not build" >&2
    exit 1
fi

(cd "$dist" && sha256sum --quiet -c SHA256SUMS) || {
    echo "refusing: an artifact in $dist changed after 'make dist'" >&2
    exit 1
}
echo "ok   $dist was built from HEAD $head"
