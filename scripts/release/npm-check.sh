#!/bin/sh
# `npm pack --dry-run` on each packed tarball's own contents, then install
# @edgelens/core from its tarball into an empty project and load it both ways.
#
# The dry run runs inside the unpacked tarball, so it lists exactly what
# a re-pack of the published manifest would ship.
set -eu
export npm_config_update_notifier=false

work=$(mktemp -d)
for tgz in /dist/*.tgz; do
    echo "=== npm pack --dry-run: $(basename "$tgz")"
    dir="$work/$(basename "$tgz" .tgz)"
    mkdir -p "$dir"
    tar -x -z -C "$dir" -f "$tgz"
    (cd "$dir/package" && npm pack --dry-run --ignore-scripts 2>&1)
done

echo "=== install @edgelens/core from dist"
mkdir "$work/consumer"
cd "$work/consumer"
npm init -y >/dev/null
npm install --no-audit --no-fund --loglevel=error /dist/edgelens-core-*.tgz
node -e 'const m = require("@edgelens/core"); if (!m.EdgeLensClient) process.exit(1); console.log("ok   require @edgelens/core")'
node --input-type=module -e 'import { EdgeLensClient } from "@edgelens/core"; if (!EdgeLensClient) process.exit(1); console.log("ok   import @edgelens/core")'
