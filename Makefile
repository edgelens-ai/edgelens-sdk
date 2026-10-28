# Root Makefile for edgelens-sdk.
#
# ----------------------------------------------------------------------------
# TWO MEANINGS OF "ci" IN THIS REPO, DELIBERATELY SEPARATE.
# ----------------------------------------------------------------------------
# The `ci/` tree is CUSTOMER-FACING: a GitHub Action under `ci/github-action/`
# and a GitLab include under `ci/gitlab/` that end-users wire into THEIR
# pipelines to run their own EdgeLens-driven test suites. It is a published
# artefact, not our gate.
#
# This Makefile is the SDK's OWN gate: `make test` runs the full offline test
# suite of every component in this repo. The two never mix: a change to the
# shipped action does not touch this file, and a change to this file does not
# touch the action.
#
# WHAT IS NOT RUN HERE.
#
# `examples/pytest/Makefile` already runs the demo suite in its own CI image.
# It is pinned, graded, and is the test harness for the end-to-end
# device-driven demo. `make test` here does NOT reproduce or re-wrap its
# work; the demo tree stays its own target, invoked by
# `make -C examples/pytest demo`.
#
# `examples/robot/*.robot` and `examples/playwright/*.spec.ts` are DEMOS,
# not unit tests. They need robotframework and playwright-with-browsers
# respectively, and are specifically out of scope here. Nothing in this
# Makefile builds, installs or runs them.
#
# ----------------------------------------------------------------------------
# EVERY TARGET RUNS IN A CONTAINER.
# ----------------------------------------------------------------------------
# Nothing is installed on the host. The suite's dependencies are declared in
# requirements.test.txt (python) and core/typescript/package-lock.json
# (typescript), resolved once at image-build time, and run at test time with
# `--network none` so a test that silently starts depending on a live service
# fails here rather than in a demo.
#
# ----------------------------------------------------------------------------
# TARGETS
# ----------------------------------------------------------------------------
#   make test            Full gate. Runs the python half and the typescript
#                        half in sequence; exit code is the worse of the two
#                        so a failure in one half cannot hide behind a pass
#                        in the other.
#   make test-python     Python half only (every Python test file listed
#                        under TEST_PYTHON_PATHS).
#   make test-typescript TypeScript half only (vitest run against
#                        core/typescript/tests).
#   make test-go         k6 extension only: `go test ./...` in
#                        integrations/k6, in a pinned golang container.
#                        Needs the network once to fill the module cache.
#   make test-image      Build both test images if either is missing.
#                        A no-op when they both already exist locally.
#   make test-rebuild    Force-rebuild both test images, then run `make test`.
#                        Needed after a Dockerfile.test, Dockerfile.test-
#                        typescript, requirements.test.txt or TypeScript
#                        package-lock.json change -- `make test` deliberately
#                        does not rebuild on content changes.
#   make dist            Build every Python sdist and wheel and both npm
#                        tarballs into dist/, from the committed tree at
#                        HEAD (uncommitted edits are not packaged). Records
#                        the commit and a SHA256SUMS for the publish targets.
#   make dist-check      Check dist/: twine check, a clean-container install
#                        and import of every wheel (edgelens-sdk from dist/,
#                        never PyPI), npm pack --dry-run, and a scan for
#                        files that must not ship.
#   make publish-pypi    Upload dist/'s Python artifacts, edgelens-sdk first.
#                        Needs PYPI_TOKEN; refuses a missing or stale dist/.
#   make publish-npm     Publish dist/'s npm tarballs, @edgelens/core first.
#                        Needs NPM_TOKEN; refuses a missing or stale dist/.
#   make version-check   Fail, naming the file and the value, unless every
#                        copy of the version agrees with VERSION. dist,
#                        dist-check, image and every publish target run it
#                        against HEAD first.
#   make set-version V=x.y.z
#                        Write x.y.z to VERSION and every copy, regenerate
#                        both package-lock.json files with npm in a
#                        container, then run version-check.
#   make image           Build ci/docker/Dockerfile from HEAD, tagged
#                        <version>, <major>.<minor> and latest, labelled
#                        with the version and the HEAD commit.
#   make image-smoke     Run the in-image smoke checks against <version>.
#   make publish-image   Push the three image tags. Refuses unless
#                        version-check passes, the image was built from
#                        HEAD, and <version> is not already in the registry.
#                        RELEASING.md has the whole procedure.
#   make help            This list.

PODMAN ?= podman

PY_IMAGE ?= edgelens-sdk-test:0.1
TS_IMAGE ?= edgelens-sdk-test-typescript:0.1

# The one place the python test components are enumerated. Each component is
# run in its own pytest process (see test-python below for why), and each
# path is relative to the mounted /sdk, which is where the live tree lands
# at run time. Adding a new tests/ directory means adding it here (and
# nowhere else).
TEST_PYTHON_COMPONENTS = \
  core/python/tests \
  integrations/cli/tests \
  integrations/mcp/tests \
  integrations/pytest/tests \
  integrations/robot/tests \
  ci/github-action/scripts/test_parse_junit.py

# ARGS passes extra arguments through to pytest / vitest for a one-off run:
#   make test-python ARGS='-k ssrf -s'
#   make test-typescript ARGS='--reporter=verbose'
ARGS ?=

REPO := $(CURDIR)

# The Go toolchain for the k6 extension, pinned by digest. GO_MODCACHE is a
# named podman volume so the module download happens once, not per run.
GO_IMAGE    ?= docker.io/library/golang:1.24.13-bookworm@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac
GO_MODCACHE ?= edgelens-sdk-gomod

# Release tooling. DIST_IMAGE carries the pinned build and twine
# (Dockerfile.dist); NODE_IMAGE is the same pinned node base the TypeScript
# test image uses. PY_IMAGE_BASE is the bare python base: wheels are
# install-checked in it so nothing preinstalled can satisfy an import.
DIST_IMAGE    ?= edgelens-sdk-dist:0.1
NODE_IMAGE    ?= docker.io/library/node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0
PY_IMAGE_BASE ?= docker.io/library/python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
DIST          := $(REPO)/dist
RELEASE       := $(REPO)/scripts/release

# The one version every package, the image and the release tag carry.
# scripts/release/version.py checks and rewrites every copy of it.
VERSION := $(shell cat $(REPO)/VERSION)
MAJOR   := $(word 1,$(subst ., ,$(VERSION)))
MINOR   := $(word 2,$(subst ., ,$(VERSION)))

# The CI image. Released tags are immutable: publish-image refuses a
# version the registry already has. Credentials come from `podman login`
# or REGISTRY_AUTH_FILE, never from a file in this repo.
IMAGE      ?= docker.io/edgelensai/edgelens-sdk
IMAGE_TAGS  = $(VERSION) $(MAJOR).$(MINOR) latest

# wheel filename glob : import name, one pair per Python package.
WHEEL_IMPORTS = \
  edgelens_sdk-*.whl:edgelens \
  edgelens_cli-*.whl:edgelens_cli \
  edgelens_mcp-*.whl:edgelens_mcp \
  pytest_edgelens-*.whl:pytest_edgelens \
  robotframework_edgelens-*.whl:EdgeLensLibrary

.PHONY: help test test-python test-typescript test-go test-image test-rebuild \
        test-image-python test-image-typescript \
        test-rebuild-python test-rebuild-typescript \
        version-check version-check-head set-version \
        dist dist-check dist-image publish-pypi publish-npm \
        image image-smoke publish-image

help:
	@sed -n 's/^#   //p' $(MAKEFILE_LIST) | sed -n '/^make /,/^$$/p'

## The gate. test-python's exit code wins when it fails: a red python half is
## the one that must not be hidden by a green typescript half, because the
## python half is where the ten regressions live. The && chain gives that
## shape -- test-typescript only runs after test-python passed. A failure on
## either side exits non-zero.
test: test-python test-typescript

## Python half -- the whole offline suite listed in TEST_PYTHON_PATHS.
##
## --network none is the point: these tests are offline by definition, so a
## test that quietly starts depending on a live service fails here instead of
## at demo time. See the SSRF defense-in-depth tests in the suite --
## the whole class of defect it names only ever matters on a denied network.
##
## The repo is bind-mounted read-only at /sdk and the editable installs the
## image did at build time resolve through it, so a file:line in pytest
## output is a path a reader can open directly rather than one translated
## out of a baked-in copy.
##
## -p no:cacheprovider: the mount is read-only; without this, pytest's
## .pytest_cache write dies with EROFS and the suite can't run at all.
##
## ONE PYTEST PROCESS PER COMPONENT. Four of the six components each carry a
## `tests/__init__.py` making their `tests/` an importable package named
## `tests`, and each has a `conftest.py` -- pytest registers it as a plugin
## by its dotted module name, so a single session sees four modules all
## claiming the name `tests.conftest` and the plugin manager refuses the
## second (ValueError: Plugin already registered under a different name,
## measured 2026-10-18 on pytest 9.1.1 under both prepend and importlib
## import modes). Splitting the run gives each component its own plugin
## registry; the component-level loop here is also how the exit code gets to
## be the worst status across the whole suite rather than only the first
## red.
##
## The loop reports PASS / FAIL per component and keeps running after a red,
## so one broken component does not hide the state of the five that follow.
## The final `[ $$fail -eq 0 ]` carries the suite's actual verdict out as
## the target's exit code.
test-python: test-image-python
	@fail=0; \
	for p in $(TEST_PYTHON_COMPONENTS); do \
	  echo "=== $$p ==="; \
	  $(PODMAN) run --rm --network none \
	    -v $(REPO):/sdk:ro,z -w /sdk \
	    $(PY_IMAGE) \
	    python3 -m pytest -p no:cacheprovider "$$p" $(ARGS) \
	    || fail=1; \
	done; \
	[ $$fail -eq 0 ]

## TypeScript half -- vitest against core/typescript/tests.
##
## --network none for the same reason the python half uses it: SSRF checks
## in base_url_ssrf.test.ts assert refusal on an off-network fetch, and a
## test that reaches past the loopback here is a test that stopped being a
## unit test.
##
## No bind-mount, by design: see the Dockerfile.test-typescript header.
## node_modules lives inside the image; a change under core/typescript/src
## or core/typescript/tests wants `make test-rebuild`.
test-typescript: test-image-typescript
	$(PODMAN) run --rm --network none \
	  $(TS_IMAGE) \
	  npm test --silent -- $(ARGS)

## k6 extension -- go test in integrations/k6. Not part of `make test`
## yet: unlike the other halves it needs the network on its first run, to
## fill the module cache from go.sum. -mod=readonly keeps go.mod and go.sum
## exactly as committed; the source mount is read-only besides.
test-go:
	$(PODMAN) run --rm \
	  -v $(REPO)/integrations/k6:/src:ro,z -w /src \
	  -v $(GO_MODCACHE):/go/pkg/mod \
	  -e GOFLAGS=-mod=readonly -e GOTOOLCHAIN=local -e GOCACHE=/tmp/go-build \
	  $(GO_IMAGE) \
	  go test ./... $(ARGS)

## Build both images on absence. `podman image exists` is the check rather
## than a timestamp, because no host file's mtime tracks an image layer -- a
## change under core/python/edgelens/ needs no rebuild either (the mount
## picks it up).
test-image: test-image-python test-image-typescript

test-image-python:
	@$(PODMAN) image exists $(PY_IMAGE) \
	  || $(PODMAN) build -f Dockerfile.test -t $(PY_IMAGE) .

test-image-typescript:
	@$(PODMAN) image exists $(TS_IMAGE) \
	  || $(PODMAN) build -f Dockerfile.test-typescript -t $(TS_IMAGE) .

## Force-rebuild. The only approved route to pick up a Dockerfile.test,
## Dockerfile.test-typescript, requirements.test.txt, package.json or
## package-lock.json change -- the default `make test` deliberately will
## not notice one.
test-rebuild: test-rebuild-python test-rebuild-typescript
	$(MAKE) test

test-rebuild-python:
	$(PODMAN) build -f Dockerfile.test -t $(PY_IMAGE) .

test-rebuild-typescript:
	$(PODMAN) build -f Dockerfile.test-typescript -t $(TS_IMAGE) .

## ---------------------------------------------------------------------------
## Release artifacts. RELEASING.md is the procedure; these are its steps.
## ---------------------------------------------------------------------------

dist-image:
	@$(PODMAN) image exists $(DIST_IMAGE) \
	  || $(PODMAN) build -f Dockerfile.dist -t $(DIST_IMAGE) .

## version-check reads the working tree, restricted to tracked files so an
## untracked scratch tree cannot fail it. version-check-head reads the
## commit instead: dist, the image and the publish targets ship HEAD, so HEAD
## is what has to agree.
version-check: dist-image
	@git ls-files | $(PODMAN) run --rm -i --network none \
	  -v $(REPO):/sdk:ro,z $(DIST_IMAGE) \
	  python3 /sdk/scripts/release/version.py check /sdk --files-from -

version-check-head: dist-image
	@git archive HEAD | $(PODMAN) run --rm -i --network none \
	  -v $(RELEASE):/release:ro,z $(DIST_IMAGE) \
	  sh -c 'mkdir /tmp/src && tar -x -C /tmp/src && python3 /release/version.py check /tmp/src'

## The lock files are npm's to write: each is regenerated from its manifest,
## core first because the plugin's lock records core's version through its
## file: devDependency. Network stays on for npm's registry metadata.
set-version: dist-image
	@test -n "$(V)" || { echo "usage: make set-version V=x.y.z" >&2; exit 1; }
	@git ls-files | $(PODMAN) run --rm -i --network none \
	  -v $(REPO):/sdk:z $(DIST_IMAGE) \
	  python3 /sdk/scripts/release/version.py set /sdk $(V) --files-from -
	@for d in core/typescript integrations/playwright; do \
	  echo "lock $$d/package-lock.json"; \
	  $(PODMAN) run --rm -e HOME=/tmp -e npm_config_update_notifier=false \
	    -v $(REPO):/sdk:z -w /sdk/$$d $(NODE_IMAGE) \
	    npm install --package-lock-only --ignore-scripts --no-audit --no-fund --loglevel=error \
	    || exit 1; \
	done
	@$(MAKE) --no-print-directory version-check

## `git archive HEAD` is the build input, so dist/ is exactly the commit it is
## stamped with: nothing untracked (a local venv, a .env, a scratch tree) can
## reach an artifact, and check-fresh.sh can hold publishing to that commit.
## Network stays on: the builds fetch hatchling and the npm dependencies.
dist: version-check-head
	@git diff --quiet HEAD -- || echo "note: uncommitted changes are not in dist/ (it builds HEAD)"
	@mkdir -p $(DIST)
	@$(PODMAN) run --rm -v $(DIST):/dist:z $(DIST_IMAGE) \
	  find /dist -mindepth 1 -delete
	git archive HEAD | $(PODMAN) run --rm -i \
	  -v $(DIST):/dist:z -v $(RELEASE):/release:ro,z \
	  $(DIST_IMAGE) sh /release/build-python.sh
	git archive HEAD | $(PODMAN) run --rm -i -e HOME=/tmp \
	  -v $(DIST):/dist:z -v $(RELEASE):/release:ro,z \
	  $(NODE_IMAGE) sh /release/build-npm.sh
	@echo "commit=$$(git rev-parse HEAD)" > $(DIST)/BUILD_INFO
	@cd $(DIST) && ls | grep -vxE 'BUILD_INFO|SHA256SUMS' | xargs sha256sum > SHA256SUMS
	@echo "=== dist/ (built from $$(git rev-parse --short HEAD))"
	@cd $(DIST) && ls -l | sed 1d | awk '{printf "%10d  %s\n", $$5, $$9}'

## Every check runs against dist/ as built; none rebuilds it. The install
## check uses one fresh container per wheel, so no wheel can lean on another
## one's leftovers.
dist-check: version-check-head
	@test -f $(DIST)/BUILD_INFO || { echo "no dist/; run 'make dist' first" >&2; exit 1; }
	@echo "=== twine check"
	$(PODMAN) run --rm --network none -v $(DIST):/dist:ro,z $(DIST_IMAGE) \
	  sh -c 'twine check --strict /dist/*.whl /dist/*.tar.gz'
	@echo "=== artifact contents"
	$(PODMAN) run --rm --network none \
	  -v $(DIST):/dist:ro,z -v $(REPO):/sdk:ro,z $(DIST_IMAGE) \
	  python3 /sdk/scripts/release/check-artifacts.py /dist /sdk
	@echo "=== wheel install and import (clean container per wheel)"
	@for pair in $(WHEEL_IMPORTS); do \
	  $(PODMAN) run --rm -e HOME=/tmp \
	    -v $(DIST):/dist:ro,z -v $(RELEASE):/release:ro,z \
	    $(PY_IMAGE_BASE) sh /release/install-check.sh "$${pair%%:*}" "$${pair##*:}" \
	    || exit 1; \
	done
	@echo "=== npm"
	$(PODMAN) run --rm -e HOME=/tmp \
	  -v $(DIST):/dist:ro,z -v $(RELEASE):/release:ro,z \
	  $(NODE_IMAGE) sh /release/npm-check.sh
	@echo "=== dist-check passed"

## Core first: every integration depends on edgelens-sdk, and an index that
## does not have it yet cannot satisfy an install of the rest. The token goes
## in by name (-e PYPI_TOKEN), never as a value on a command line.
publish-pypi: version-check-head
	@sh $(RELEASE)/check-fresh.sh $(DIST) PYPI_TOKEN
	$(PODMAN) run --rm -e PYPI_TOKEN -v $(DIST):/dist:ro,z $(DIST_IMAGE) sh -c '\
	  set -e; export TWINE_USERNAME=__token__ TWINE_PASSWORD="$$PYPI_TOKEN" TWINE_NON_INTERACTIVE=1; \
	  twine upload /dist/edgelens_sdk-*; \
	  for p in edgelens_cli edgelens_mcp pytest_edgelens robotframework_edgelens; do \
	    twine upload /dist/$$p-*; \
	  done'

## npm expands ${NPM_TOKEN} inside .npmrc when it reads it, so the file holds
## the variable's name, not the token. Core first: the plugin's peer range
## names it.
publish-npm: version-check-head
	@sh $(RELEASE)/check-fresh.sh $(DIST) NPM_TOKEN
	$(PODMAN) run --rm -e HOME=/tmp -e NPM_TOKEN -v $(DIST):/dist:ro,z $(NODE_IMAGE) sh -c '\
	  set -e; echo "//registry.npmjs.org/:_authToken=\$${NPM_TOKEN}" > "$$HOME/.npmrc"; \
	  npm publish /dist/edgelens-core-*.tgz --access public; \
	  npm publish /dist/edgelens-playwright-plugin-*.tgz --access public'

## ---------------------------------------------------------------------------
## The CI image. Built from `git archive HEAD` like dist/, so the revision
## label names exactly what is inside it and nothing untracked reaches it.
## ---------------------------------------------------------------------------

image: version-check-head
	@ctx=$$(mktemp -d) && trap 'rm -rf "$$ctx"' EXIT && \
	git archive HEAD | tar -x -C "$$ctx" && \
	$(PODMAN) build -f "$$ctx/ci/docker/Dockerfile" \
	  --label org.opencontainers.image.version=$(VERSION) \
	  --label org.opencontainers.image.revision=$$(git rev-parse HEAD) \
	  $(foreach t,$(IMAGE_TAGS),-t $(IMAGE):$(t)) \
	  "$$ctx"
	@$(PODMAN) images --filter reference=$(IMAGE) --format '{{.Repository}}:{{.Tag}}  {{.ID}}'

image-smoke:
	$(PODMAN) run --rm $(IMAGE):$(VERSION) /bin/bash -lc '\
	  set -eu; \
	  echo "=== python ==="; python --version; pip show edgelens-sdk edgelens-cli | grep -E "^(Name|Version)"; \
	  echo "=== edgelens cli ==="; edgelens --version; \
	  echo "=== node ==="; node --version; \
	  echo "=== npm globals ==="; npm ls -g --depth 0 2>/dev/null | grep edgelens; \
	  echo "=== playwright ==="; npx --no -y playwright --version || true; \
	  echo "=== k6 ==="; k6 version; \
	  echo "=== OK ==="'

## Every refusal runs before the first push, so a refused publish pushes
## nothing.
publish-image: version-check-head
	@sh ci/docker/check-release-pins.sh ci/docker/Dockerfile ci/github-action/action.yml
	@PODMAN="$(PODMAN)" sh $(RELEASE)/check-image.sh $(IMAGE) $(VERSION) $(IMAGE_TAGS)
	@for t in $(IMAGE_TAGS); do \
	  $(PODMAN) push $(IMAGE):$$t || exit 1; \
	done
