# edgelensai/edgelens-sdk — Docker image for CI pipelines

Pre-built image with every EdgeLens runtime your CI needs:

- **Python 3.12** + `pytest` + `edgelens-sdk` (Python SDK) + `edgelens-cli` + `edgelens-pytest`
- **Node 22** + Playwright (Chromium / Firefox / WebKit) + `@edgelens/core` + `@edgelens/playwright-plugin`
- **k6** binary

Base: [`mcr.microsoft.com/playwright:v1.55.0-noble`](https://mcr.microsoft.com/en-us/product/playwright/about) — Ubuntu 24.04 with the browsers pre-installed.

## Use

### GitHub Actions

```yaml
jobs:
  edgelens-tests:
    runs-on: ubuntu-latest
    container:
      image: edgelensai/edgelens-sdk:0.2.4
    steps:
      - uses: actions/checkout@v4
      - run: pytest          # pytest + edgelens SDK already installed
      - run: npx playwright test  # @edgelens/playwright-plugin already linked
        env:
          EDGELENS_API_KEY: ${{ secrets.EDGELENS_API_KEY }}
```

### GitLab CI

```yaml
edgelens:
  image: edgelensai/edgelens-sdk:0.2.4
  script:
    - pytest
    - edgelens session list
  variables:
    EDGELENS_API_KEY: $EDGELENS_API_KEY
```

### Local dev

```sh
docker run --rm -it \
  -v "$PWD:/workspace" \
  -e EDGELENS_API_KEY \
  edgelensai/edgelens-sdk:0.2.4 \
  pytest
```

## Build

The image targets live in the SDK repo's root Makefile and take the
version from the root `VERSION` file. Run them from the repo root:

```sh
make dist            # the wheels and npm tarballs the image installs
make image           # build, tagged <version>
make image-smoke     # run the in-image smoke checks against <version>
make image-plan      # print the tags publish-image would push; pushes nothing
make publish-image   # push and verify the tags (requires registry login)
```

For `VERSION` x.y.z the image is `edgelensai/edgelens-sdk:x.y.z`. Image
tags carry no `v`. `make publish-image` also moves `:x.y` and `:latest`
to it, each only when no released version is higher: `:x.y` follows the
highest x.y.z, `:latest` the highest version overall. Publishing an older
version or a patch to an older line therefore never moves them backwards.
The released versions are the x.y.z tags the registry lists.

The image is labelled `org.opencontainers.image.version` (the version) and
`org.opencontainers.image.revision` (the commit it was built from).

The build context is `git archive HEAD` of the SDK repo plus the wheels
and npm tarballs from `dist/`, which `make image` first checks against
`dist/SHA256SUMS` and the commit in `dist/BUILD_INFO`. The image installs
exactly the files published to PyPI and npm, so no sources or tests ship
in it, and the revision label names the commit both were built from.

`make publish-image` refuses to push when the version check fails, when
the local image was not built from the current commit, or when the
registry holds `:x.y.z` as a different image: released version tags are
immutable. When the registry already holds `:x.y.z` as this very image,
as after a push that stopped part way, it skips that tag and completes the
moving tags. After pushing it reads every tag back from the registry and
fails unless each names the image it pushed. Log in with
`podman login docker.io` first; no credentials are read from the
repository.

## Build args

| Arg | Default | Purpose |
|---|---|---|
| `K6_VERSION` | `v0.55.0` | k6 binary version downloaded from Grafana's GitHub releases; bump `K6_SHA256` with it |
| `PLAYWRIGHT_VERSION` | `1.55.0` | `@playwright/test` version; matches the base image's browsers |

## Smoke checks

`make image-smoke` runs the built image with this script:

- `python --version`
- `pip show edgelens-sdk edgelens-cli edgelens-pytest`
- `edgelens --version`
- `node --version`
- `npm ls -g --depth 0` (`@edgelens/core`, `@edgelens/playwright-plugin`, `@playwright/test`)
- `npx playwright --version`
- `k6 version`

All of these must pass before the image is pushed.
