# k6 example — sustained inference benchmark

Soak test that holds the face detector at the inference engine for 10
minutes and gates on fps + latency thresholds. Uses `xk6-edgelens`.

## Setup

```bash
# Build a custom k6 binary with the EdgeLens extension
go install go.k6.io/xk6/cmd/xk6@latest
xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6

export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
```

## Run

```bash
./k6 run bench.js

# Shorter for smoke
./k6 run --duration 30s bench.js

# Different load profile
./k6 run --vus 1 --duration 5m bench.js
```

## What it does

| Phase | What |
|---|---|
| `setup()` | Allocates one session, deploys the face model, starts inference. |
| `default` (per VU iter) | Polls `device.inference.stats()`, emits `inference_fps` + `inference_latency_ms` metrics. |
| `teardown()` | Releases the session. |
| Thresholds | `inference_fps avg>15`, `inference_latency_ms p(95)<100` — k6 exits non-zero on breach. |

## Files

```
examples/k6/
├── README.md
├── bench.js                # 10-minute soak
└── smoke.js                # 30-second smoke test
```

## CI gating

```yaml
- run: |
    xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6
    ./k6 run --quiet bench.js
  env:
    EDGELENS_API_KEY: ${{ secrets.EDGELENS_API_KEY }}
```

`./k6 run` exits 99 when a threshold breaches — CI sees a non-zero exit
and the job fails. Pair with the `--summary-export=summary.json` flag
if you want to post the numbers as a PR comment.
