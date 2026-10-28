# Examples

Working example projects for each integration. Copy-pasteable with an
EdgeLens API key.

Every project follows the same pattern: clone the repo, install
deps, set `EDGELENS_API_KEY`, run.

| Subdir | Framework | Demonstrates |
|---|---|---|
| [`pytest/`](./pytest/) | pytest | Face-detector benchmark suite, multi-model parametrize, `recamagined` custom binary, OS-agnostic smoke |
| [`playwright/`](./playwright/) | Playwright | Browser + camera in one test, per-OS projects, kiosk screenshot diff |
| [`k6/`](./k6/) | k6 | 10-minute soak with `inference_fps` + `inference_latency_ms` thresholds, 30s smoke variant |
| [`robot/`](./robot/) | Robot Framework | Suite-scoped device, template-parametrized FPS sweep, tagged regression subsets |
| [`mlflow/`](./mlflow/) | MLflow | One-run-per-version, nested-children sweep across model versions |
| [`wandb/`](./wandb/) | Weights & Biases | Final-stats, streaming snapshots, Bayesian sweep |

## What's in each project

```
examples/<framework>/
├── README.md          # how to run + what it tests
├── (manifest)         # requirements.txt | package.json | etc.
├── (config)           # pyproject.toml | playwright.config.ts | etc.
├── tests/ or *.py     # the actual code
└── models/README.md   # where to put your .cvimodel(s)
```

Models are *not* committed — drop your own in `models/` and the tests
run. See each project's `models/README.md` for naming conventions.

## Common setup

```bash
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
```

Add to your shell rc file for convenience. Every example honors this
variable (or its framework-specific override flag).
