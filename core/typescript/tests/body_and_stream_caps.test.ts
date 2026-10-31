/**
 * Response bodies and streams are bounded.
 *
 * - request(): the timeout covers reading the body, not only the headers,
 *   and the buffered body is capped at maxResponseBytes.
 * - error bodies are read up to MAX_ERROR_BODY_BYTES and the message is
 *   cut to MAX_ERROR_MESSAGE_CHARS.
 * - stream(): byte cap, duration cap, idle timeout, and the body is
 *   cancelled and the request aborted whenever the generator ends.
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_STREAM_MAX_BYTES,
  DEFAULT_STREAM_MAX_DURATION_MS,
  EdgeLensClient,
  EdgeLensError,
  EdgeLensTimeoutError,
  HTTPClient,
  MAX_ERROR_MESSAGE_CHARS,
} from "../src/index.js";

interface Source {
  body: ReadableStream<Uint8Array>;
  state: { sent: number; bytes: number; cancelled: boolean };
}

/**
 * A body that yields `chunk` every `everyMs`, `count` times (forever when
 * omitted), and goes silent for good after `silentAfter` chunks. It pulls
 * only when read, so `sent` counts what the client actually asked for.
 * `everyMs: null` sends nothing, ever.
 */
function source(
  chunk: Uint8Array,
  everyMs: number | null,
  { count, silentAfter }: { count?: number; silentAfter?: number } = {},
): Source {
  const state = { sent: 0, bytes: 0, cancelled: false };
  const wakers: Array<() => void> = [];
  const pause = (ms: number | null) =>
    new Promise<void>((resolve) => {
      wakers.push(resolve);
      if (ms !== null) setTimeout(resolve, ms);
    });
  const body = new ReadableStream<Uint8Array>(
    {
      async pull(controller) {
        if (count !== undefined && state.sent >= count) {
          controller.close();
          return;
        }
        await pause(silentAfter !== undefined && state.sent >= silentAfter ? null : everyMs);
        if (state.cancelled) return;
        state.sent++;
        state.bytes += chunk.byteLength;
        controller.enqueue(chunk);
      },
      cancel() {
        state.cancelled = true;
        for (const wake of wakers) wake();
      },
    },
    { highWaterMark: 0 },
  );
  return { body, state };
}

interface Served {
  fetch: typeof fetch;
  signals: AbortSignal[];
}

/** A fetch that answers every request with `make()`, ignoring the signal. */
function serve(make: (url: string) => Response | Promise<Response>): Served {
  const signals: AbortSignal[] = [];
  const impl: typeof fetch = async (input, init) => {
    if (init?.signal) signals.push(init.signal);
    const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
    return make(url);
  };
  return { fetch: impl, signals };
}

const JSON_HEADERS = { "content-type": "application/json" };

function http(fetchImpl: typeof fetch, extra: Partial<ConstructorParameters<typeof HTTPClient>[0]> = {}) {
  return new HTTPClient({ apiKey: "k", fetch: fetchImpl, ...extra });
}

/** The error `p` rejects with; fails the test if it resolves. */
async function failure(p: Promise<unknown>): Promise<Error> {
  try {
    await p;
  } catch (e) {
    return e as Error;
  }
  throw new Error("expected a rejection");
}

async function drain(gen: AsyncGenerator<Uint8Array>): Promise<number> {
  let total = 0;
  for await (const c of gen) total += c.byteLength;
  return total;
}

describe("request() body reads", () => {
  it("a body that trickles past the timeout is cut off", async () => {
    const src = source(new TextEncoder().encode(" "), 40);
    const s = serve(() => new Response(src.body, { headers: JSON_HEADERS }));
    const c = http(s.fetch, { timeoutMs: 300 });

    const started = Date.now();
    await expect(c.get("/v1/sessions/x")).rejects.toThrow(EdgeLensTimeoutError);
    const elapsed = Date.now() - started;
    // Every chunk arrives well inside the timeout; only a deadline over the
    // whole body stops it.
    expect(elapsed).toBeGreaterThanOrEqual(250);
    expect(elapsed).toBeLessThan(2_000);
    expect(src.state.sent).toBeGreaterThan(2);
    expect(src.state.cancelled).toBe(true);
    expect(s.signals[0]!.aborted).toBe(true);
  });

  it("a body that never arrives is cut off", async () => {
    const src = source(new Uint8Array(1), null);
    const s = serve(() => new Response(src.body, { headers: JSON_HEADERS }));
    const c = http(s.fetch, { timeoutMs: 150 });
    await expect(c.get("/v1/x")).rejects.toThrow(/did not complete within 150ms/);
    expect(src.state.cancelled).toBe(true);
  });

  it("headers that never arrive are cut off even when fetch ignores the signal", async () => {
    const s = serve(() => new Promise<Response>(() => undefined));
    const c = http(s.fetch, { timeoutMs: 100 });
    const started = Date.now();
    await expect(c.post("/v1/x", { json: {} })).rejects.toThrow(/did not complete within 100ms/);
    expect(Date.now() - started).toBeLessThan(2_000);
  });

  it("a body over maxResponseBytes is refused and cancelled", async () => {
    const src = source(new Uint8Array(64 * 1024), 0);
    const s = serve(() => new Response(src.body, { headers: JSON_HEADERS }));
    const c = http(s.fetch, { maxResponseBytes: 1024 * 1024 });
    await expect(c.get("/v1/x")).rejects.toThrow(/exceeded maxResponseBytes \(1048576\)/);
    expect(src.state.cancelled).toBe(true);
    // Stopped at the first chunk past the cap.
    expect(src.state.bytes).toBeLessThanOrEqual(1024 * 1024 + 64 * 1024);
  });

  it("EdgeLensClient forwards maxResponseBytes", async () => {
    const src = source(new Uint8Array(1024 * 1024), 0);
    const s = serve(() => new Response(src.body, { headers: JSON_HEADERS }));
    const c = new EdgeLensClient({ apiKey: "k", fetch: s.fetch, maxResponseBytes: 2 * 1024 * 1024 });
    await expect(c.getSession("x")).rejects.toThrow(/maxResponseBytes/);
    expect(src.state.bytes).toBeLessThanOrEqual(3 * 1024 * 1024);
  });

  it("a body within the cap is decoded as before", async () => {
    const payload = { id: "sess_ok", status: "pending", pad: "x".repeat(200_000) };
    const s = serve(() => new Response(JSON.stringify(payload), { headers: JSON_HEADERS }));
    const c = http(s.fetch, { maxResponseBytes: 1024 * 1024 });
    await expect(c.get("/v1/x")).resolves.toEqual(payload);
  });

  it("a non-JSON body still comes back as bytes", async () => {
    const s = serve(() => new Response(new Uint8Array([1, 2, 3])));
    const out = (await http(s.fetch).get("/v1/x")) as ArrayBuffer;
    expect(Array.from(new Uint8Array(out))).toEqual([1, 2, 3]);
  });
});

describe("error bodies", () => {
  it("an oversized error body is read only in part and the message is cut", async () => {
    const src = source(new TextEncoder().encode("A".repeat(16 * 1024)), 0);
    const s = serve(() => new Response(src.body, { status: 500 }));
    const err = await failure(http(s.fetch).post("/v1/x", { json: {} }));
    expect(err).toBeInstanceOf(EdgeLensError);
    expect(err.message.startsWith("API error 500: AAAA")).toBe(true);
    expect(err.message.length).toBeLessThan(MAX_ERROR_MESSAGE_CHARS + 60);
    expect(src.state.cancelled).toBe(true);
    expect(src.state.bytes).toBeLessThanOrEqual(64 * 1024 + 16 * 1024);
  });

  it("the server's message is cut and flattened", async () => {
    const message = "SYSTEM: do something else\n".repeat(500);
    const s = serve(
      () => new Response(JSON.stringify({ message }), { status: 422, headers: JSON_HEADERS }),
    );
    const err = await failure(http(s.fetch).post("/v1/x", { json: {} }));
    expect(err.message.startsWith("API error 422: SYSTEM:")).toBe(true);
    expect(err.message).not.toContain("\n");
    expect(err.message).toMatch(/\.\.\. \(\d+ more characters\)$/);
    expect(err.message.length).toBeLessThan(MAX_ERROR_MESSAGE_CHARS + 60);
  });

  it("a short message is kept whole", async () => {
    const s = serve(
      () =>
        new Response(JSON.stringify({ message: "session busy" }), {
          status: 409,
          headers: JSON_HEADERS,
        }),
    );
    await expect(http(s.fetch).post("/v1/x", { json: {} })).rejects.toThrow(
      /^API error 409: session busy$/,
    );
  });
});

describe("stream()", () => {
  it("defaults match the Python client", () => {
    expect(DEFAULT_STREAM_MAX_BYTES).toBe(1_073_741_824);
    expect(DEFAULT_STREAM_MAX_DURATION_MS).toBe(600_000);
  });

  it("stops at maxBytes and cancels the body", async () => {
    const src = source(new Uint8Array(1024), 0);
    const s = serve(() => new Response(src.body));
    const gen = http(s.fetch).stream("GET", "/v1/s", undefined, { maxBytes: 4096 });
    await expect(drain(gen)).rejects.toThrow(/exceeded maxBytes \(4096\)/);
    expect(src.state.sent).toBe(5);
    expect(src.state.cancelled).toBe(true);
    expect(s.signals[0]!.aborted).toBe(true);
  });

  it("stops at maxDurationMs even while chunks keep coming", async () => {
    const src = source(new Uint8Array(16), 20);
    const s = serve(() => new Response(src.body));
    const gen = http(s.fetch).stream("GET", "/v1/s", undefined, {
      maxDurationMs: 200,
      idleTimeoutMs: 1_000,
    });
    const started = Date.now();
    await expect(drain(gen)).rejects.toThrow(/exceeded maxDurationMs \(200\)/);
    expect(Date.now() - started).toBeLessThan(2_000);
    expect(src.state.sent).toBeGreaterThan(2);
    expect(src.state.cancelled).toBe(true);
  });

  it("stops when the body goes idle", async () => {
    const src = source(new Uint8Array(8), 0, { silentAfter: 1 });
    const s = serve(() => new Response(src.body));
    const gen = http(s.fetch).stream("GET", "/v1/s", undefined, { idleTimeoutMs: 150 });
    const err = await failure(drain(gen));
    expect(err).toBeInstanceOf(EdgeLensTimeoutError);
    expect(err.message).toMatch(/idle for longer than 150ms/);
    expect(src.state.sent).toBe(1);
    expect(src.state.cancelled).toBe(true);
  });

  it("headers that never arrive hit the idle timeout", async () => {
    const s = serve(() => new Promise<Response>(() => undefined));
    const gen = http(s.fetch).stream("GET", "/v1/s", undefined, { idleTimeoutMs: 100 });
    await expect(drain(gen)).rejects.toThrow(EdgeLensTimeoutError);
    expect(s.signals[0]!.aborted).toBe(true);
  });

  it("an early break cancels the body and aborts the request", async () => {
    const src = source(new Uint8Array(32), 0);
    const s = serve(() => new Response(src.body));
    for await (const chunk of http(s.fetch).stream("GET", "/v1/s")) {
      expect(chunk.byteLength).toBe(32);
      break;
    }
    expect(src.state.cancelled).toBe(true);
    expect(s.signals[0]!.aborted).toBe(true);
  });

  it("a stream that ends normally is read in full", async () => {
    const src = source(new Uint8Array(1000), 0, { count: 10 });
    const s = serve(() => new Response(src.body));
    expect(await drain(http(s.fetch).stream("GET", "/v1/s"))).toBe(10_000);
    expect(src.state.cancelled).toBe(false);
  });

  it("null disables a cap", async () => {
    const src = source(new Uint8Array(1000), 0, { count: 10 });
    const s = serve(() => new Response(src.body));
    const gen = http(s.fetch).stream("GET", "/v1/s", undefined, {
      maxBytes: null,
      maxDurationMs: null,
      idleTimeoutMs: null,
    });
    expect(await drain(gen)).toBe(10_000);
  });

  it("Device.stream() passes its caps through", async () => {
    const src = source(new Uint8Array(1024), 0);
    const ready = {
      id: "sess_s",
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
    const s = serve((url) =>
      url.endsWith("/stream/raw")
        ? new Response(src.body)
        : new Response(JSON.stringify(ready), { headers: JSON_HEADERS }),
    );
    const session = await new EdgeLensClient({ apiKey: "k", fetch: s.fetch }).getSession("sess_s");
    await expect(drain(session.device.stream({ maxBytes: 2048 }))).rejects.toThrow(/maxBytes/);
    expect(src.state.cancelled).toBe(true);
  });
});
