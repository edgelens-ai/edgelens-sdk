# pytest example — face detection latency test

Complete pytest project showing `edgelens-pytest` against the
`stock-os` inference engine.

## End-to-end demo

To run face detection on a real reCamera running reCamaginedOS, from
session to release, follow [DEMO.md](DEMO.md).

## Setup

There is nothing to install. Both the offline tests and the demo run in
a container image built from this repository, which carries the client
library, the pytest plugin and this example's own dependencies:

```bash
cd examples/pytest
make -C ../.. image                    # once
```

The example's third-party dependencies are declared in
`requirements.txt`, and the image build installs from it — so adding one
is an edit to that file and a rebuild, not something assembled by hand.
`edgelens-pytest` and `edgelens` are not on PyPI yet and are built from
this repository's own sources during that build.

Then set your API key (get one from the customer portal at
`/app/keys` → Create). Copy the example env file and fill in your
values:

```bash
cp .env.example .env
# edit .env — set EDGELENS_API_KEY, and uncomment and set EDGELENS_BASE_URL if self-hosting
```

`.env` is gitignored — never commit it. If you'd rather not use a file,
export the key directly instead:

```bash
export EDGELENS_API_KEY=el_test_xxxxxxxxxxxxxxxxxxxx
```

## Run

The platform base URL is resolved in this precedence order:

1. `--edgelens-base-url=...` CLI flag (if set)
2. `EDGELENS_BASE_URL` env var
3. `https://api.edgelens.ai` (default)

Malicious hosts (private IPs, IMDS, plaintext http://) are rejected at
construction time by the SDK's URL validator,
so the env fallback is safe.

```bash
# Cloud (default — `https://api.edgelens.ai`):
pytest

# Self-hosted / dev, from env (put it in .env):
export EDGELENS_BASE_URL=https://api.example.com
pytest

# Or one-off from the CLI:
pytest --edgelens-base-url=https://api.example.com
```

Persist the URL for a project by adding to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "--strict-markers --edgelens-base-url=https://api.example.com"
```

### Common flags

```bash
# Pin the OS tier (default is whichever the test asks for):
pytest --edgelens-os=stock-os
pytest --edgelens-os=recamagined

# Verbose + slowest 5 tests:
pytest -v --durations=5

# Skip device allocation — tests that request a device are skipped, so
# unit-test logic that wraps the SDK runs without real hardware:
pytest --edgelens-skip-allocation
```

## What it tests

| Test | OS | Assertion |
|---|---|---|
| `test_face_latency` | stock-os | p95 latency < 100 ms on the face model |
| `test_face_fps_floor` | stock-os | avg fps ≥ 15 |
| `test_custom_binary_runs_clean` | recamagined | user-shipped binary deploys to `/userdata/Models/` and runs clean |
| `test_device_info` | either | hostname + hardware fields populated |
| `test_demo_face_detection` | recamagined | at least one face with score ≥ 0.5; inference latency in range |

The repo layout mirrors what a real customer would have — one
`tests/` directory, one `models/` directory, no nonstandard scaffolding.

## Files

```
examples/pytest/
├── README.md
├── DEMO.md                 # runbook for the end-to-end face-detection demo
├── requirements.txt
├── pyproject.toml
├── tests/
│   ├── test_face_detector.py
│   ├── test_demo_end_to_end.py  # end-to-end demo: deploy, run inference, assert on faces
│   ├── demo_inference.py        # demo payload paths, device command, output parser
│   └── test_demo_parsing.py     # offline unit tests for the demo parser
└── models/
    └── README.md           # provenance + usage for scrfd_500m_kps_int8.cvimodel
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `fixture 'device' not found` | the plugin is missing from the image, so it was built before the plugin was added to it, or the run is not using the image | Rebuild with `make -C ../.. image` and re-run `make demo` |
| `httpx.ConnectError: Name or service not known` | `--edgelens-base-url` missing; SDK fell back to the cloud default and DNS for `api.edgelens.ai` failed (or you're on a private network without it) | Pass `--edgelens-base-url=...` or add to `pyproject.toml` `addopts` |
| `Session sess_… ended in state error before becoming ready` | No device matching the session's device type and OS was available, e.g. all are in use | Retry later; if it keeps happening, contact EdgeLens support with the session id |
| `AuthenticationError: Invalid or expired API key` on every call | API key revoked, mistyped, or for the wrong environment | Mint a fresh key in the portal |
| `AuthenticationError: API key does not have permission: …` | The key isn't permitted to request this device type or OS (for the demo, `recamera-2002` / `recamagined`), or the requested session is longer than the key allows | Use a key scoped for that device type and OS; contact EdgeLens support to get one |

## Adapting to your project

Drop your own model in `models/` and update the path in
`tests/test_face_detector.py`. The fixture handles allocation +
wait_ready + release; you write the assertion.
