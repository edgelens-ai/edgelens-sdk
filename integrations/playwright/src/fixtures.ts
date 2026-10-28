/**
 * Playwright fixtures. The standard import:
 *
 *   import { test, expect } from "@edgelens/playwright-plugin";
 *
 *   test("display playback", async ({ device }) => {
 *     await device.display.play("https://example.com/video.mp4");
 *     // ... assertions
 *   });
 *
 * Two scopes:
 *
 * - **worker-scoped** (`workerDevice`, `workerSession`, `workerClient`)
 *   — one camera per worker process, reused across every test in that
 *   worker. The right default when sessions take 30+s to provision and
 *   tests are mostly read-only.
 *
 * - **test-scoped** (`device`, `session`, `client`) — fresh camera per
 *   test. Picks the worker-scoped one up by default but can be
 *   overridden via `test.use({ session: ... })`.
 */

import { test as base } from "@playwright/test";
import { EdgeLensClient } from "@edgelens/core";
import type { Device, Session } from "@edgelens/core";

import {
  DEFAULTS,
  allocateSession,
  buildClient,
  releaseSession,
  type EdgelensFixtureOptions,
} from "./lifecycle.js";

export interface EdgelensWorkerFixtures {
  edgelensOptions: EdgelensFixtureOptions;
  workerClient: EdgeLensClient;
  workerSession: Session;
  workerDevice: Device;
}

export interface EdgelensTestFixtures {
  /** Fresh per-test client. Defaults to the worker-scoped one. */
  client: EdgeLensClient;
  /** Fresh per-test session. Defaults to the worker-scoped one. */
  session: Session;
  /** Fresh per-test device. Defaults to the worker-scoped one. */
  device: Device;
}

export const test = base.extend<EdgelensTestFixtures, EdgelensWorkerFixtures>({
  // -------- worker-scoped: client / session / device -----------------------

  // The default fixture options. Override in playwright.config.ts via:
  //   use: { edgelensOptions: { session: { os: "recamagined" } } }
  edgelensOptions: [
    { waitReadyTimeoutMs: DEFAULTS.waitReadyTimeoutMs, waitReadyPollMs: DEFAULTS.waitReadyPollMs },
    { option: true, scope: "worker" },
  ],

  workerClient: [
    async ({ edgelensOptions }, use) => {
      const client = buildClient(edgelensOptions);
      await use(client);
    },
    { scope: "worker" },
  ],

  workerSession: [
    async ({ workerClient, edgelensOptions }, use) => {
      const session = await allocateSession(workerClient, edgelensOptions);
      try {
        await use(session);
      } finally {
        await releaseSession(session);
      }
    },
    { scope: "worker", timeout: 0 },
  ],

  workerDevice: [
    async ({ workerSession }, use) => {
      await use(workerSession.device);
    },
    { scope: "worker" },
  ],

  // -------- test-scoped: passthrough to worker-scoped by default ----------

  client: async ({ workerClient }, use) => {
    await use(workerClient);
  },

  session: async ({ workerSession }, use) => {
    await use(workerSession);
  },

  device: async ({ workerSession }, use) => {
    await use(workerSession.device);
  },
});

export { expect } from "@playwright/test";
