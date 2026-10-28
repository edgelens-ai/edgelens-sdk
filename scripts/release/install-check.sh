#!/bin/sh
# Install one wheel from /dist into this (fresh) container and import it.
#
# Usage: install-check.sh WHEEL_GLOB IMPORT_NAME
#
# edgelens-sdk is installed from /dist first, by path, so that resolving an
# integration's `edgelens-sdk>=x,<y` finds it already satisfied and never
# asks PyPI for that name. Third-party dependencies (httpx, click, mcp, ...)
# do come from PyPI. The check then proves where edgelens-sdk came from.
set -eu

wheel_glob=$1
module=$2

export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

core=$(ls /dist/edgelens_sdk-*.whl)
wheel=$(ls /dist/$wheel_glob)

pip install --quiet --user --no-warn-script-location "$core"
pip install --quiet --user --no-warn-script-location "$wheel"

python3 - "$module" <<'EOF'
import importlib, json, sys
from importlib.metadata import distribution, entry_points

module = sys.argv[1]
importlib.import_module(module)

origin = json.loads(distribution("edgelens-sdk").read_text("direct_url.json") or "{}")
url = origin.get("url", "")
if not url.startswith("file:///dist/"):
    sys.exit(f"edgelens-sdk did not come from dist/: {url or 'no direct_url'}")

if module == "pytest_edgelens":
    plugins = {ep.name: ep.value for ep in entry_points(group="pytest11")}
    if plugins.get("pytest_edgelens") != "pytest_edgelens.plugin":
        sys.exit(f"pytest11 entry point missing: {plugins}")

print(f"ok   import {module} (edgelens-sdk {distribution('edgelens-sdk').version} from {url})")
EOF
