import { describe, expect, it, vi } from "vitest";

import { EdgeLensClient } from "@edgelens/core";
import type { Session } from "@edgelens/core";

import {
  allocateSession,
  buildClient,
  releaseSession,
} from "../src/lifecycle.js";
import { edgelensProjects } from "../src/projects.js";

const READY = {
  id: "sess_pw",
  status: "ready" as const,
  device: {
    mac: "aa:bb:cc:00:00:01",
    host: "192.0.2.42",
    ssh_port: 30008,
    ssh_user: "recamera",
    ssh_password: "x".repeat(24),
    os: "stock-os" as const,
  },
};

interface FakeCall {
  method: string;
  url: string;
  body: string | undefined;
}

function fakeFetch(handler: (call: FakeCall) => { status?: number; json: unknown }): {
  fetch: typeof fetch;
  calls: FakeCall[];
} {
  const calls: FakeCall[] = [];
  const impl: typeof fetch = async (input, init) => {
    const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? init.body : undefined;
    const call = { method, url, body };
    calls.push(call);
    const res = handler(call);
    return new Response(JSON.stringify(res.json), {
      status: res.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  };
  return { fetch: impl, calls };
}

describe("buildClient", () => {
  it("threads apiKey + baseUrl + custom fetch through", () => {
    const ff = fakeFetch(() => ({ json: {} }));
    const c = buildClient({
      apiKey: "el_test_x",
      baseUrl: "https://api.test.edgelens.ai",
      client: { fetch: ff.fetch },
    });
    expect(c).toBeInstanceOf(EdgeLensClient);
  });
});

describe("allocateSession", () => {
  it("creates + waits for ready, returns Session", async () => {
    let getHits = 0;
    const ff = fakeFetch((call) => {
      if (call.method === "POST" && new URL(call.url).pathname === "/v1/sessions") {
        return { json: { id: "sess_pw", status: "flashing" } };
      }
      if (call.method === "GET" && new URL(call.url).pathname === "/v1/sessions/sess_pw") {
        getHits++;
        if (getHits < 2) return { json: { id: "sess_pw", status: "flashing" } };
        return { json: READY };
      }
      return { status: 599, json: { error: "no handler" } };
    });

    const client = buildClient({
      apiKey: "el_test_x",
      client: { fetch: ff.fetch },
    });
    const session = await allocateSession(client, {
      session: { deviceType: "recamera-2002", os: "stock-os", timeoutS: 600 },
      waitReadyTimeoutMs: 5_000,
      waitReadyPollMs: 10,
    });
    expect(session.status).toBe("ready");
    expect(session.device.host).toBe("192.0.2.42");

    const create = ff.calls.find((c) => c.method === "POST")!;
    const sent = JSON.parse(create.body!);
    expect(sent.device_type).toBe("recamera-2002");
    expect(sent.os).toBe("stock-os");
    expect(sent.timeout).toBe(600);
  });

  it("propagates errors when session never reaches ready", async () => {
    const ff = fakeFetch((call) => {
      if (call.method === "POST") return { json: { id: "sess_e", status: "flashing" } };
      return { json: { id: "sess_e", status: "error" } };
    });
    const client = buildClient({ apiKey: "k", client: { fetch: ff.fetch } });
    await expect(
      allocateSession(client, { waitReadyTimeoutMs: 1_000, waitReadyPollMs: 10 }),
    ).rejects.toThrow();
  });

  function clientWhoseWaitRejects(original: Error, release: () => Promise<void>) {
    const fakeSession = {
      id: "sess_wait",
      waitReady: vi.fn(async () => {
        throw original;
      }),
      release: vi.fn(release),
    };
    const client = {
      createSession: vi.fn(async () => fakeSession),
    } as unknown as EdgeLensClient;
    return { client, fakeSession };
  }

  it("releases the session when waitReady throws", async () => {
    const original = new Error("never became ready");
    const { client, fakeSession } = clientWhoseWaitRejects(original, async () => undefined);

    await expect(allocateSession(client)).rejects.toBe(original);
    expect(fakeSession.release).toHaveBeenCalledOnce();
  });

  it("rethrows the original error when the release also fails", async () => {
    const original = new Error("never became ready");
    const { client, fakeSession } = clientWhoseWaitRejects(original, async () => {
      throw new Error("release failed");
    });
    const onReleaseError = vi.fn();

    await expect(allocateSession(client, {}, onReleaseError)).rejects.toBe(original);
    expect(fakeSession.release).toHaveBeenCalledOnce();
    expect(onReleaseError).toHaveBeenCalledOnce();
    expect((onReleaseError.mock.calls[0]![0] as Error).message).toBe("release failed");
  });
});

describe("releaseSession", () => {
  it("calls .release() on the session", async () => {
    const release = vi.fn(async () => undefined);
    const fakeSession = { release } as unknown as Session;
    await releaseSession(fakeSession);
    expect(release).toHaveBeenCalledOnce();
  });

  it("no-ops on undefined session", async () => {
    await expect(releaseSession(undefined)).resolves.toBeUndefined();
  });

  it("forwards release errors to the onError callback (does not throw)", async () => {
    const release = vi.fn(async () => {
      throw new Error("teardown blew up");
    });
    const fakeSession = { release } as unknown as Session;
    const onError = vi.fn();
    await releaseSession(fakeSession, onError);
    expect(onError).toHaveBeenCalledOnce();
    expect((onError.mock.calls[0]![0] as Error).message).toBe("teardown blew up");
  });
});

describe("edgelensProjects", () => {
  it("emits one project per (deviceType, os) combo by default", () => {
    const projects = edgelensProjects({ apiKey: "k" });
    expect(projects.map((p) => p.name)).toEqual([
      "recamera-2002/stock-os",
      "recamera-2002/recamagined",
    ]);
    expect(projects[0]!.use.edgelensOptions.session?.os).toBe("stock-os");
    expect(projects[0]!.use.edgelensOptions.apiKey).toBe("k");
  });

  it("honors a custom matrix", () => {
    const projects = edgelensProjects({
      apiKey: "k",
      matrix: [{ deviceType: "recamera-2002", os: "recamagined", sessionTimeoutS: 900 }],
    });
    expect(projects).toHaveLength(1);
    expect(projects[0]!.use.edgelensOptions.session?.timeoutS).toBe(900);
  });

  it("threads baseUrl when provided", () => {
    const projects = edgelensProjects({ apiKey: "k", baseUrl: "https://staging.edgelens.ai" });
    expect(projects[0]!.use.edgelensOptions.baseUrl).toBe("https://staging.edgelens.ai");
  });
});
