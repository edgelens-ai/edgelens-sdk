/**
 * Long-running operations size their request timeout to the operation.
 *
 * exec and inference results hold the request open for the requested
 * time, so the client must wait at least that long plus a margin. Every
 * other request keeps the client's configured timeout.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EdgeLensClient } from "../src/index.js";

const READY = {
  id: "sess_t",
  status: "ready",
  device: {
    mac: "aa:bb:cc:00:00:01",
    host: "192.0.2.42",
    ssh_port: 22,
    ssh_user: "recamera",
    ssh_password: "x".repeat(24),
    os: "stock-os",
  },
};

interface Pending {
  signals: Map<string, AbortSignal>;
  fetch: typeof fetch;
}

/** Answers the session GET at once; every other request stays pending
 * until its signal aborts, and its signal is recorded by pathname. */
function pendingFetch(): Pending {
  const signals = new Map<string, AbortSignal>();
  const fetchImpl: typeof fetch = (input, init) => {
    const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
    const path = new URL(url).pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" && path === "/v1/sessions/sess_t") {
      return Promise.resolve(
        new Response(JSON.stringify(READY), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }
    const signal = init!.signal!;
    signals.set(path, signal);
    return new Promise<Response>((_, reject) => {
      signal.addEventListener("abort", () => reject(new Error("aborted")));
    });
  };
  return { signals, fetch: fetchImpl };
}

async function readySession(f: Pending, timeoutMs?: number) {
  const c = new EdgeLensClient({
    apiKey: "el_test_k",
    fetch: f.fetch,
    ...(timeoutMs !== undefined ? { timeoutMs } : {}),
  });
  return c.getSession("sess_t");
}

describe("operation-sized request timeouts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("exec(timeoutS=120) is not aborted after 60 s", async () => {
    const f = pendingFetch();
    const s = await readySession(f);
    s.device.exec("sleep 110", 120).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(60_000);
    const signal = f.signals.get("/v1/sessions/sess_t/exec");
    expect(signal).toBeDefined();
    expect(signal!.aborted).toBe(false);
  });

  it("inference.run(120) is not aborted after 60 s", async () => {
    const f = pendingFetch();
    const s = await readySession(f);
    s.device.inference.run(120).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(60_000);
    const signal = f.signals.get("/v1/sessions/sess_t/inference/results");
    expect(signal).toBeDefined();
    expect(signal!.aborted).toBe(false);
  });

  it("a plain GET is still aborted after 31 s", async () => {
    const f = pendingFetch();
    const s = await readySession(f);
    s.device.info().catch(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    const signal = f.signals.get("/v1/sessions/sess_t/info");
    expect(signal).toBeDefined();
    await vi.advanceTimersByTimeAsync(31_000);
    expect(signal!.aborted).toBe(true);
  });

  it("a larger client timeout is not lowered by exec(..., 60)", async () => {
    const f = pendingFetch();
    const s = await readySession(f, 900_000);
    s.device.exec("true", 60).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(600_000);
    const signal = f.signals.get("/v1/sessions/sess_t/exec");
    expect(signal).toBeDefined();
    expect(signal!.aborted).toBe(false);
  });
});
