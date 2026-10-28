# Playwright

`@edgelens/playwright-plugin` extends `@playwright/test` so a Playwright
test can take a real camera as a fixture — useful when you want to
verify on-device behavior end-to-end with browser-driven UX checks.

```bash
npm install -D @edgelens/playwright-plugin @edgelens/core @playwright/test
```

Requires Node 18+.

## Quickstart

```ts
// e2e/camera.spec.ts
import { readFile } from "node:fs/promises";
import { test, expect } from "@edgelens/playwright-plugin";

// deploy() uploads local file data; read the model into a Blob.
const upload = async (path: string) => ({
  name: path.split("/").pop()!,
  blob: new Blob([await readFile(path)]),
});

test("camera displays the test pattern", async ({ device, page }) => {
  await device.display.show("https://example.com/test-pattern.png");
  await device.display.waitStable();

  await page.goto(`http://${device.host}:8000/preview`);
  await expect(page).toHaveScreenshot();
});

test("inference latency", async ({ device }) => {
  await device.deploy({ model: await upload("./models/face.cvimodel") });
  await device.inference.start();
  const stats = await device.inference.run(30);
  expect(stats.fps.avg).toBeGreaterThan(15);
  expect(stats.latency_ms.p95).toBeLessThan(100);
});
```

## Fixtures

| Fixture | Scope | What |
|---|---|---|
| `device` | worker (default) | `Device` past `waitReady()` |
| `session` | worker | `Session` |
| `client` | worker | `EdgeLensClient` |
| `workerSession` | worker | Long-lived session shared across tests in the worker |

Worker-scope is the default tradeoff for sessions that take ~30 s to
provision. Tests in the same worker share a device.

## Per-OS projects

Use the `edgelensProjects` helper in `playwright.config.ts` to spin up
one project per `(deviceType, os)`:

```ts
import { defineConfig } from "@playwright/test";
import { edgelensProjects } from "@edgelens/playwright-plugin";

export default defineConfig({
  projects: [
    ...edgelensProjects({
      deviceType: "recamera-2002",
      oses: ["stock-os", "recamagined"],
    }),
  ],
});
```

Run all projects:

```bash
npx playwright test
```

Run one project:

```bash
npx playwright test --project=stock-os
```

## Patterns

### Browser + device in one test

The thing Playwright is uniquely good at:

```ts
test("kiosk shows live inference", async ({ device, page }) => {
  await device.deploy({ model: await upload("./models/person.cvimodel") });
  await device.inference.start();

  await page.goto(`http://${device.host}:8000/`);
  await expect(page.locator(".detection-count")).not.toHaveText("0", {
    timeout: 10_000,
  });
});
```

### Screenshot-diff against a deployed model

```ts
test("face detector boxes the test image", async ({ device, page }) => {
  await device.display.show("https://example.com/face-test.png");
  await device.deploy({ model: await upload("./models/face.cvimodel") });
  await device.inference.start();

  await page.goto(`http://${device.host}:8000/preview`);
  await expect(page).toHaveScreenshot("face-detected.png");
});
```

## Anti-patterns

- Hard-coding `device.host` IPs in the page URL — use the field from
  the fixture. The platform proxies it.
- Long `await page.waitForTimeout(N)` calls when you mean
  `device.display.waitStable()` or `expect(...).toBeVisible()`.
- Calling `await session.release()` from inside a test — the worker
  fixture's teardown handles it.

## Example project

Full working project: [`examples/playwright/`](../../examples/playwright/).
