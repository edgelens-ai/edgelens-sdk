# @edgelens/playwright-plugin

Playwright integration for [EdgeLens](https://edgelens.ai) — write a
Playwright test that gets a real edge AI camera as a fixture, with
auto-allocate, auto-release, and project presets for each
(deviceType, os) combination.

## Install

```sh
npm install -D @edgelens/playwright-plugin @edgelens/core @playwright/test
```

Requires Node 18+.

## Quickstart

```ts
// e2e/camera.spec.ts
import { readFile } from "node:fs/promises";
import { test, expect } from "@edgelens/playwright-plugin";

test("camera displays the test pattern", async ({ device, page }) => {
  await device.display.show("https://example.com/test-pattern.png");
  await device.display.waitStable();

  // device.host is reachable from your test process — the platform
  // proxies through to the camera-LAN device.
  await page.goto(`http://${device.host}:8000/preview`);
  await expect(page).toHaveScreenshot();
});

test("inference latency", async ({ device }) => {
  // deploy() uploads local file data.
  const blob = new Blob([await readFile("./models/face.cvimodel")]);
  await device.deploy({ model: { name: "face.cvimodel", blob } });
  await device.inference.start();
  const stats = await device.inference.run(30);
  expect(stats.fps.avg).toBeGreaterThan(15);
  expect(stats.latency_ms.p95).toBeLessThan(100);
});
```

`device` (and `session`, `client`) are **worker-scoped** by default —
one camera per worker process, shared across every test in that
worker. The right tradeoff for read-only test suites where sessions
take 30s+ to provision.

For tests that mutate device state and want isolation, use
`workerSession` directly or override in `test.use()` — see
`Test scopes` below.

## Configure

In `playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";
import { edgelensProjects } from "@edgelens/playwright-plugin";

export default defineConfig({
  projects: [
    ...edgelensProjects({
      apiKey: process.env.EDGELENS_API_KEY,
      // matrix: [{ deviceType: "recamera-2002", os: "stock-os" }],
    }),
  ],
});
```

`edgelensProjects()` emits one Playwright project per
`(deviceType, os)` combination — by default both `stock-os` and
`recamagined`. Filter with the standard Playwright `--project=...`
flag.

Or, no projects — just `use: { edgelensOptions: ... }` directly:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  use: {
    edgelensOptions: {
      apiKey: process.env.EDGELENS_API_KEY,
      session: { deviceType: "recamera-2002", os: "stock-os", timeoutS: 1800 },
    },
  },
});
```

## Fixtures

| Fixture | Scope | What |
|---|---|---|
| `client` | test | `EdgeLensClient` from `@edgelens/core`, defaults to the worker-scoped one |
| `session` | test | `Session`, defaults to the worker-scoped one |
| `device` | test | `Device` (the test surface), defaults to the worker-scoped one |
| `workerClient` | worker | One `EdgeLensClient` per worker process |
| `workerSession` | worker | One ready `Session` per worker, auto-released at worker teardown |
| `workerDevice` | worker | The `Device` from the worker-scoped session |
| `edgelensOptions` | worker | The options passed to the underlying client + lifecycle helpers (override in `use`) |

## Test scopes

**Worker-scoped (default — `device`):** one camera per worker, reused
across every test in that worker. Wall-clock-cheap, but tests share
device state — order matters and a stuck device may take other tests
down with it.

**Test-scoped:** define a custom fixture if you want a fresh device
every test:

```ts
import { test as base, allocateSession, releaseSession } from "@edgelens/playwright-plugin";

const test = base.extend<{ freshDevice: import("@edgelens/core").Device }>({
  freshDevice: async ({ workerClient, edgelensOptions }, use) => {
    const session = await allocateSession(workerClient, edgelensOptions);
    try {
      await use(session.device);
    } finally {
      await releaseSession(session);
    }
  },
});
```

## Errors

The fixtures don't swallow errors during setup — Playwright reports
fixture failures as the cause of the test failure. Teardown errors
(failed release) are swallowed by default so they don't mask the
original test failure; pass an `onError` callback to `releaseSession`
to log them.

## Develop

```sh
npm install
npm run typecheck
npm test
npm run build
```

