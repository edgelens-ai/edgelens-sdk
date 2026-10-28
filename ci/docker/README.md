# edgelensai/edgelens-sdk — Docker image for CI pipelines

Pre-built image with every EdgeLens runtime your CI needs:

- **Python 3.12** + `pytest` + `edgelens` (Python SDK) + `edgelens-cli`
- **Node 20** + Playwright (Chromium / Firefox / WebKit) + `@edgelens/core` + `@edgelens/playwright-plugin`
- **k6** binary (`xk6-edgelens` extension comes later)

Base: [`mcr.microsoft.com/playwright:v1.55.0-noble`](https://mcr.microsoft.com/en-us/product/playwright/about) — Ubuntu 24.04 with the browsers pre-installed.

## Use

### GitHub Actions

```yaml
jobs:
  edgelens-tests:
    runs-on: ubuntu-latest
    container:
      image: edgelensai/edgelens-sdk:0.1.1
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
  image: edgelensai/edgelens-sdk:0.1.1
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
  edgelensai/edgelens-sdk:0.1.1 \
  pytest
```

## Build

The image targets live in the SDK repo's root Makefile and take the
version from the root `VERSION` file. Run them from the repo root:

```sh
make image           # build, tagged <version>, <major>.<minor> and latest
make image-smoke     # run the in-image smoke checks against <version>
make publish-image   # push all three tags (requires registry login)
```

For `VERSION` 0.1.0 that is `edgelensai/edgelens-sdk:0.1.1`, `:0.1` and
`:latest`. Image tags carry no `v`. The image is labelled
`org.opencontainers.image.version` (the version) and
`org.opencontainers.image.revision` (the commit it was built from).

The build context is `git archive HEAD` of the SDK repo, because the
Dockerfile COPYs across `core/*` and `integrations/*`. Only committed
files reach the image, and the revision label names exactly that commit.

`make publish-image` refuses to push when the version check fails, when
the local image was not built from the current commit, or when the
version is already in the registry: released tags are immutable. Log in
with `podman login docker.io` first; no credentials are read from the
repository.

## Build args

| Arg | Default | Purpose |
|---|---|---|
| `K6_VERSION` | `v0.55.0` | k6 binary version downloaded from Grafana's GitHub releases |

## Smoke checks

`make image-smoke` runs the built image with this script:

- `python --version`
- `pip show edgelens-sdk edgelens-cli`
- `edgelens --version`
- `node --version`
- `npm ls -g --depth 0 | grep edgelens`
- `npx playwright --version`
- `k6 version`

All of these must pass before the image is pushed.
