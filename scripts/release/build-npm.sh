#!/bin/sh
# Build and pack both npm packages into /dist.
#
# Runs inside the pinned node image. stdin is `git archive HEAD`, so only
# committed files are packed.
#
# @edgelens/playwright-plugin develops against the in-repo core through a
# `file:../../core/typescript` devDependency. That path means nothing to a
# user who installs the published tarball, so the staged copy drops it before
# `npm pack`; the published manifest keeps only the `^x.y.z` peer range.
set -eu
export npm_config_update_notifier=false

src=$(mktemp -d)
tar -x -C "$src"

echo "=== npm: core/typescript"
cd "$src/core/typescript"
npm ci --no-audit --no-fund --loglevel=error
npm run --silent build >/dev/null
npm pack --pack-destination /dist --loglevel=error

echo "=== npm: integrations/playwright"
cd "$src/integrations/playwright"
npm ci --no-audit --no-fund --loglevel=error
npm run --silent build >/dev/null
npm pkg delete 'devDependencies.@edgelens/core'
npm pack --pack-destination /dist --loglevel=error
