# Playwright example — kiosk integration test

Complete Playwright project showing `@edgelens/playwright-plugin`
driving both a real camera and a browser pointed at the camera's
on-device web UI.

## Setup

```bash
cd examples/playwright
npm install
export EDGELENS_API_KEY=el_live_xxxxxxxxxxxxxxxxxxxx
```

## Run

```bash
# All projects (stock-os + recamagined)
npx playwright test

# One project
npx playwright test --project=stock-os

# Headed (watch the browser)
npx playwright test --headed
```

## What it tests

| Test | Project | Asserts |
|---|---|---|
| `kiosk shows test pattern` | stock-os | `device.display.show` updates the preview page screenshot |
| `inference holds the latency budget` | stock-os | p95 < 100 ms after deploying the face model |
| `camera serves preview on $host` | stock-os | Browser can reach the camera HTTP server through the preview URL the platform provides |
| `custom binary logs to stdout` | recamagined | Deployed binary writes the expected line |

## Files

```
examples/playwright/
├── README.md
├── package.json
├── playwright.config.ts
├── tests/
│   └── camera.spec.ts
└── models/
    └── README.md
```

## Adapting

Drop your own URL into `display.show` / `display.play` and your own
model into `device.deploy`. Browser-side assertions are normal
Playwright matchers — `toHaveScreenshot`, `toBeVisible`, etc.
