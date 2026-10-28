# Releasing

How the packages in this repository are built and published. Every step
runs in a podman container; nothing is installed on the host.

## Packages

| Package | Registry | Source |
|---|---|---|
| `edgelens-sdk` (imports as `edgelens`) | PyPI | `core/python` |
| `edgelens-cli` | PyPI | `integrations/cli` |
| `edgelens-mcp` | PyPI | `integrations/mcp` |
| `pytest-edgelens` | PyPI | `integrations/pytest` |
| `robotframework-edgelens` | PyPI | `integrations/robot` |
| `@edgelens/core` | npm | `core/typescript` |
| `@edgelens/playwright-plugin` | npm | `integrations/playwright` |
| `edgelensai/edgelens-sdk` (CI image) | Docker Hub | `ci/docker/Dockerfile` |

The PyPI name `edgelens` belongs to an unrelated project. The core Python
distribution is `edgelens-sdk`; its import package is still `edgelens`.

## Versioning

One version covers everything this repository releases: the five PyPI
packages, the two npm packages, the GitHub Action, the
`edgelensai/edgelens-sdk` image and the GitHub release. They are released
together, at the same number.

- **`VERSION`** at the repository root is the source. Every other copy is
  either derived from it at build time or checked against it.
- **Semver.** While the version is `0.x`, a minor bump (`0.1` to `0.2`) may
  break the API; a patch bump does not. From `1.0.0` on, only a major bump
  may break it.
- **Git tags** are `v<version>`, for example `v0.1.0`, created when the
  public repository is released. A release tag is immutable: it is never
  moved or re-pointed, and there is no moving major-version tag. Users pin
  the action by its exact tag:
  `uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.0`.
- **Image tags** carry no `v`: `edgelensai/edgelens-sdk:<version>`,
  `:<major>.<minor>` and `:latest`, for example `:0.1.0`, `:0.1` and
  `:latest`. A released `<version>` tag is never pushed again.

### What is derived and what is checked

Derived, so there is nothing to keep in step:

- each Python package's version (hatchling reads `__version__` from the
  package itself);
- the Python client's `User-Agent` and the Robot Framework library
  version (both read `__version__`);
- the image tags and its `org.opencontainers.image.version` label (the
  Makefile reads `VERSION`).

Checked by `make version-check`, which names each file and value that
disagrees with `VERSION`:

- `__version__` in each of the five Python packages;
- both `package.json` versions and both `package-lock.json` files;
- the `edgelens-sdk>=X.Y.Z,<X.(Y+1)` range in each integration, and the
  `@edgelens/core` `^X.Y.Z` ranges;
- the TypeScript client's `User-Agent`;
- the `image` default in `ci/github-action/action.yml`;
- every action reference and every pinned `edgelensai/edgelens-sdk` tag in
  the repository's files.

`make dist`, `make dist-check`, `make image` and every publish target run
the same check against HEAD first, so a mismatch stops the build.

## 1. Set the version

```sh
make set-version V=0.1.1
```

This writes `VERSION` and every checked copy, regenerates both
`package-lock.json` files with npm in a container (never by hand), then
runs `make version-check`. Run `make test`, and commit: the build packages
the commit, not the working tree.

## 2. Build and check

```sh
make dist        # sdists, wheels and npm tarballs into dist/, from HEAD
make dist-check  # twine check, install-and-import, npm pack --dry-run, content scan
```

`make dist` builds from `git archive HEAD`, records the commit in
`dist/BUILD_INFO` and checksums every artifact into `dist/SHA256SUMS`.
`make dist-check` must pass before anything is uploaded.

The playwright plugin uses `@edgelens/core` from this repository during
development (a `file:` devDependency). `make dist` removes that entry from
the packed manifest, so the published package carries only the version
range.

## 3. Publish

Publish in this order, each step only after the one before it is live:

1. **The GitHub release** of the public repository, with its `v<version>`
   tag. The package metadata links to
   `https://github.com/edgelens-ai/edgelens-sdk` and the action is used from
   it, so it goes first and every link on PyPI and npm resolves.
2. **The core on PyPI**, then **the four integrations**: every integration
   depends on `edgelens-sdk`, and an index without the new core cannot
   install them.
3. **npm**: `@edgelens/core`, then the playwright plugin, whose peer range
   names it.
4. **The image.**

```sh
PYPI_TOKEN=... make publish-pypi   # edgelens-sdk, then the four integrations
NPM_TOKEN=...  make publish-npm    # @edgelens/core, then the playwright plugin
make image                         # build from HEAD, tagged and labelled
make image-smoke                   # in-image smoke checks
make publish-image                 # push :<version>, :<major>.<minor>, :latest
```

`publish-pypi` and `publish-npm` refuse to run when their token is unset,
when `dist/` is missing, when HEAD has moved since `make dist`, or when an
artifact in `dist/` no longer matches its checksum. Rebuild with
`make dist` and check again in any of those cases.

`publish-image` refuses when the version check fails, when the local image
was not built from HEAD, or when `<version>` already exists in the
registry. Every refusal comes before the first push.

Tokens are read from the environment and passed into the container by name.
Use a PyPI API token scoped to these projects and an npm automation token
for the `@edgelens` scope. Log in to Docker Hub with `podman login
docker.io`; no registry credentials live in this repository.
