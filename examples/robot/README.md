# Robot Framework example — keyword-driven QA

Robot Framework suite using `robotframework-edgelens` for a QA-team-style
keyword-driven test pass.

## Setup

```bash
cd examples/robot
pip install -r requirements.txt
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
```

## Run

```bash
# Full suite
robot tests/

# One file
robot tests/face_detector.robot

# Filter by tag
robot --include latency tests/
```

## What it tests

| Suite | OS | Asserts |
|---|---|---|
| `tests/face_detector.robot` | stock-os | p95 latency < 100 ms; fps ≥ 15; multi-model fps floor |
| `tests/recamagined.robot` | recamagined | Custom binary exit code; deployed model loads |
| `tests/smoke.robot` | either | Device info populated, hostname reachable |

Tags: `:tags: latency`, `:tags: throughput`, `:tags: regression`.

## Files

```
examples/robot/
├── README.md
├── requirements.txt
├── tests/
│   ├── face_detector.robot
│   ├── recamagined.robot
│   └── smoke.robot
└── resources/
    └── common.resource     # shared keywords
```

## CI

```yaml
- run: |
    pip install robotframework-edgelens
    robot --include regression tests/
  env:
    EDGELENS_API_KEY: ${{ secrets.EDGELENS_API_KEY }}
```

Robot exits non-zero on any failing test. JUnit XML for downstream
parsing: `robot --output result.xml --xunit junit.xml tests/`.
