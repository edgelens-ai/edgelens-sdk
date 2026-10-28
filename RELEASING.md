# Releasing

How the packages in this repository are built and published. Every step
runs in a container; nothing is installed on the host. Locally the
Makefile uses podman; the release workflow runs the same targets under
docker (see [release-workflow](#release-workflow)).

## Packages

| Package | Registry | Source |
|---|---|---|
| `edgelens-sdk` (imports as `edgelens`) | PyPI | `core/python` |
| `edgelens-cli` | PyPI | `integrations/cli` |
| `edgelens-mcp` | PyPI | `integrations/mcp` |
| `edgelens-pytest` | PyPI | `integrations/pytest` |
| `edgelens-robot` | PyPI | `integrations/robot` |
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
  `uses: edgelens-ai/edgelens-sdk/ci/github-action@v0.2.1`.
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

Pushing the release tag `v<version>` publishes everything, through the
workflow below. The local `make publish-*` targets remain as a manual
fallback.

## release-workflow

`.github/workflows/release.yml` runs on every pushed tag matching
`v*.*.*`, and by hand (**Actions → release → Run workflow**) with a `tag`
input. Run it by hand to publish a tag that predates the workflow, such as
`v0.2.0`: start it from `main`, and it checks out the tag you name.

```
build ──┬── pypi-sdk ── pypi-integrations (cli, mcp, pytest, robot) ── npm
        └── image
```

- **build** checks out the tag and fails unless it equals `v` + `VERSION`.
  It runs `make version-check`, `make dist`, `make dist-check` and
  `make image` under docker (`PODMAN=docker VOL_RO=:ro VOL_RW=`, because
  the runner has no SELinux to relabel for), and uploads `dist/` as the
  `dist` artifact. The image is built here as a check only.
- **pypi-sdk** (environment `pypi-edgelens-sdk`) verifies `dist/` against
  the build's commit and `SHA256SUMS`, then uploads the `edgelens-sdk`
  wheel and sdist with trusted publishing.
- **pypi-integrations** runs only after **pypi-sdk** succeeds, because
  every integration depends on `edgelens-sdk`. It is one job per project,
  `edgelens-cli`, `edgelens-mcp`, `edgelens-pytest` and `edgelens-robot`,
  each in its own environment `pypi-<project>`, doing the same as
  **pypi-sdk** for that project. PyPI matches a trusted publisher on
  owner, repository, workflow and environment, so each project needs an
  environment of its own.
- Before uploading, every PyPI job asks PyPI which files it already holds
  for the version. A file PyPI holds with the same sha256 as the built one
  is left out of the upload, and the job uploads only what is missing, or
  nothing. A file PyPI holds under the same name with a different sha256,
  or a file for the version that the build did not make, fails the job.
- **npm** (environment `npm`) runs only after every PyPI job succeeds. It
  publishes `@edgelens/core`, then `@edgelens/playwright-plugin`, from the
  built tarballs with `--provenance`, with trusted publishing and npm
  11.5.1 or later. A version already on npm is skipped when it is the same
  tarball, which is the case after a first manual publish (below), and
  fails the job otherwise.
- **image** (environment `dockerhub`) checks out the same commit, logs in
  to Docker Hub with the `DOCKERHUB_TOKEN` secret, rebuilds the image
  (`make image`), runs `make image-smoke`, and pushes it with
  `make publish-image`, whose refusals all run before the first push.
  The image is rebuilt rather than passed from **build** because it runs
  to gigabytes; both builds use the same commit, digest-pinned bases and a
  checksummed k6.

Every action the workflow uses is pinned to a full commit SHA, with its
version in a comment. Only one run per tag goes at a time. `make
workflow-lint` runs `actionlint` (and shellcheck) over the workflow in a
pinned container with no network; run it after any change to the file.

**Publishing `v0.2.0` by hand.** That tag carries a `check-image.sh` that
does not recognise docker's "no such manifest" reply, so the **image** job
refuses it before pushing anything. Publish that one image with the manual
fallback below, from a checkout of `v0.2.0`.

A failed step stops its job and every job that needs it. PyPI and npm
never accept the same file twice, so a re-run is safe only because each
job skips what is already published from the same build: after a partial
upload, re-run the failed jobs. A re-run after a rebuild produces files
with different hashes and fails rather than publishing a second copy.

### One-time setup

Do these once, before the first run.

**PyPI.** Add five pending trusted publishers (PyPI → Your account →
Publishing → Add a new pending publisher → GitHub), one per project, each
with its own environment. Every one has owner `edgelens-ai`, repository
name `edgelens-sdk` and workflow name `release.yml`:

| PyPI project name | Environment name |
|---|---|
| `edgelens-sdk` | `pypi-edgelens-sdk` |
| `edgelens-cli` | `pypi-edgelens-cli` |
| `edgelens-mcp` | `pypi-edgelens-mcp` |
| `edgelens-pytest` | `pypi-edgelens-pytest` |
| `edgelens-robot` | `pypi-edgelens-robot` |

PyPI refuses a second pending publisher whose owner, repository, workflow
and environment match one already registered for another project, which
is why the environments differ. The first upload creates the project and
turns the pending publisher into a normal one.

**npm.** Trusted publishing cannot be configured for a package that does
not exist yet, so each of `@edgelens/core` and
`@edgelens/playwright-plugin` needs one first publish by the maintainer:

1. Run the workflow for the release. PyPI publishes; the **npm** job fails,
   because nothing on npm trusts it yet.
2. Download that run's `dist` artifact, check it, and publish the two
   tarballs from it, core first (`npm login` opens a browser; `npm
   publish` asks for a one-time password if the account has 2FA):

   ```sh
   gh run download <run-id> --repo edgelens-ai/edgelens-sdk --name dist --dir dist
   (cd dist && sha256sum --strict -c SHA256SUMS)
   podman run --rm -it -e HOME=/tmp -v "$PWD/dist":/dist:ro,z \
     docker.io/library/node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 \
     sh -c 'npm login --auth-type=web &&
            npm publish /dist/edgelens-core-0.2.0.tgz --access public &&
            npm publish /dist/edgelens-playwright-plugin-0.2.0.tgz --access public'
   ```

   Replace `0.2.0` with the version being released.
3. On npmjs.com, for each package: **Settings → Trusted publishing →
   GitHub Actions**, with organization or user `edgelens-ai`, repository
   `edgelens-sdk`, workflow filename `release.yml` and environment `npm`.
   A new trusted publisher must make its first successful publish within
   two days, so do this shortly before the next release.
4. Re-run the failed **npm** job. It finds both versions already published
   from the same tarballs and skips them.

From the next release on, npm publishes from the workflow alone.

**Docker Hub.** Create the public repository `edgelensai/edgelens-sdk`
if it does not exist. Create an access token with read and write access to
it, and store it as the secret `DOCKERHUB_TOKEN` in the `dockerhub`
environment (not as a repository secret). Docker Hub's OIDC connection
could replace the token, but only on a Team or Business plan.

**GitHub.** The workflow uses seven environments:

- `pypi-edgelens-sdk`
- `pypi-edgelens-cli`
- `pypi-edgelens-mcp`
- `pypi-edgelens-pytest`
- `pypi-edgelens-robot`
- `npm`
- `dockerhub`

GitHub creates an environment the first time a run references it, but
with no protection rules, so create all seven in the repository's
**Settings → Environments** before the first run and set the rules by
hand. For each, under deployment branches and tags choose **Selected
branches and tags** with the tag rule `v*`, and add the branch rule `main`
as well, so a run started by hand from `main` (to publish a tag that
predates the workflow) can deploy. Optionally add required reviewers, so a
person approves every publish.

### Manual fallback

The Makefile targets publish the same `dist/` from a local machine, in the
same order: PyPI core, the integrations, npm, then the image.

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

Tokens are read from the environment and passed into the container by
name; use short-lived tokens scoped to these packages and revoke them
afterwards. Log in to Docker Hub with `podman login docker.io`; no registry
credentials live in this repository.
