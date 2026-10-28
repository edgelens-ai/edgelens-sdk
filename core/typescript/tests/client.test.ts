import { describe, expect, it } from "vitest";

import {
  AuthenticationError,
  DeviceError,
  EdgeLensClient,
  SessionError,
  RetryPolicy,
} from "../src/index.js";
import { makeFetch } from "./helpers.js";

const READY: object = {
  id: "sess_test",
  status: "ready",
  device: {
    mac: "aa:bb:cc:00:00:01",
    host: "192.0.2.42",
    ssh_port: 30007,
    ssh_user: "recamera",
    ssh_password: "x".repeat(24),
    os: "stock-os",
  },
};

describe("EdgeLensClient construction", () => {
  it("throws AuthenticationError when no key is provided", () => {
    const prev = process.env.EDGELENS_API_KEY;
    delete process.env.EDGELENS_API_KEY;
    try {
      expect(() => new EdgeLensClient({})).toThrowError(AuthenticationError);
    } finally {
      if (prev !== undefined) process.env.EDGELENS_API_KEY = prev;
    }
  });

  it("reads EDGELENS_API_KEY from env", () => {
    const prev = process.env.EDGELENS_API_KEY;
    process.env.EDGELENS_API_KEY = "el_test_env";
    try {
      const c = new EdgeLensClient({});
      expect(c).toBeDefined();
    } finally {
      if (prev !== undefined) process.env.EDGELENS_API_KEY = prev;
      else delete process.env.EDGELENS_API_KEY;
    }
  });
});

describe("session lifecycle", () => {
  it("createSession POSTs the right body and returns a flashing Session", async () => {
    const f = makeFetch().on("POST", "/v1/sessions", {
      json: { id: "sess_t1", status: "flashing" },
    });
    const c = new EdgeLensClient({ apiKey: "el_test_k", fetch: f.fetch });
    const s = await c.createSession({
      deviceType: "recamera-2002",
      os: "stock-os",
      timeoutS: 600,
    });
    expect(s.id).toBe("sess_t1");
    expect(s.status).toBe("flashing");

    expect(f.calls).toHaveLength(1);
    const sent = JSON.parse(f.calls[0]!.body!);
    expect(sent).toEqual({
      device_type: "recamera-2002",
      os: "stock-os",
      timeout: 600,
    });
    expect(f.calls[0]!.headers["authorization"]).toBe("Bearer el_test_k");
  });

  it("waitReady polls until status=ready then exposes device", async () => {
    let calls = 0;
    const f = makeFetch()
      .on("POST", "/v1/sessions", {
        json: { id: "sess_w", status: "flashing" },
      })
      .on("GET", "/v1/sessions/sess_w", () => {
        calls++;
        if (calls < 2) return { json: { id: "sess_w", status: "flashing" } };
        return { json: READY };
      });

    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    const s = await c.createSession();
    await s.waitReady(10_000, 10);
    expect(s.status).toBe("ready");
    expect(s.device.host).toBe("192.0.2.42");
    expect(s.device.os).toBe("stock-os");
    expect(s.device.ssh().port).toBe(30007);
  });

  it("waitReady raises SessionError on error state", async () => {
    const f = makeFetch()
      .on("POST", "/v1/sessions", { json: { id: "sess_e", status: "flashing" } })
      .on("GET", "/v1/sessions/sess_e", { json: { id: "sess_e", status: "error" } });

    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    const s = await c.createSession();
    await expect(s.waitReady(5_000, 10)).rejects.toBeInstanceOf(SessionError);
  });

  it("session.device throws if not ready yet", async () => {
    const f = makeFetch().on("POST", "/v1/sessions", {
      json: { id: "sess_p", status: "flashing" },
    });
    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    const s = await c.createSession();
    expect(() => s.device).toThrowError(SessionError);
  });

  it("release() DELETEs and is idempotent", async () => {
    let deletes = 0;
    const f = makeFetch()
      .on("POST", "/v1/sessions", { json: READY })
      .on("DELETE", "/v1/sessions/sess_test", () => {
        deletes++;
        return { json: { ...(READY as object), status: "released" } };
      });
    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    const s = await c.createSession();
    await s.release();
    await s.release();
    expect(deletes).toBe(1);
  });
});

describe("device operations", () => {
  async function readySession(f: ReturnType<typeof makeFetch>) {
    f.on("POST", "/v1/sessions", { json: READY });
    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    return c.createSession();
  }

  it("exec proxies to the platform", async () => {
    const f = makeFetch().on("POST", "/v1/sessions/sess_test/exec", {
      json: { stdout: "uptime\n", stderr: "", exit_code: 0 },
    });
    const s = await readySession(f);
    const r = await s.device.exec("uptime");
    expect(r.exit_code).toBe(0);
    expect(r.stdout).toBe("uptime\n");
  });

  it("deploy uploads model, config and files as multipart parts", async () => {
    const f = makeFetch().on("POST", "/v1/sessions/sess_test/deploy", {
      json: { success: true },
    });
    const s = await readySession(f);
    const result = await s.device.deploy({
      model: { name: "face.cvimodel", blob: new Blob(["MODEL"]) },
      config: { name: "face.json", blob: new Blob(["CONFIG"]) },
      files: [{ name: "my_inference", blob: new Blob(["BIN"]) }, new Blob(["IMG"])],
    });
    expect(result.success).toBe(true);

    const call = f.calls.at(-1)!;
    expect(call.rawBody).toBeInstanceOf(FormData);
    expect(call.headers["content-type"]).toBeUndefined();
    const form = call.rawBody as FormData;
    const entries: [string, File][] = [];
    form.forEach((value, key) => entries.push([key, value as File]));
    expect(entries.map(([key]) => key)).toEqual(["model", "config", "file_0", "file_1"]);
    const parts: Record<string, [string, string]> = {};
    for (const [key, file] of entries) {
      parts[key] = [file.name, await file.text()];
    }
    expect(parts).toEqual({
      model: ["face.cvimodel", "MODEL"],
      config: ["face.json", "CONFIG"],
      file_0: ["my_inference", "BIN"],
      file_1: ["file_1", "IMG"],
    });
  });

  it("deploy without model throws DeviceError and sends nothing", async () => {
    const f = makeFetch();
    const s = await readySession(f);
    const before = f.calls.length;
    await expect(
      s.device.deploy({} as unknown as Parameters<typeof s.device.deploy>[0]),
    ).rejects.toBeInstanceOf(DeviceError);
    expect(f.calls.length).toBe(before);
  });

  it("deploy never sends a JSON body", async () => {
    const f = makeFetch().on("POST", "/v1/sessions/sess_test/deploy", {
      json: { success: true },
    });
    const s = await readySession(f);
    await s.device.deploy({ model: new Blob(["MODEL"]) });
    const call = f.calls.at(-1)!;
    expect(call.headers["content-type"]).not.toBe("application/json");
    expect(typeof call.rawBody).not.toBe("string");
  });

  it("inference.start fails on recamagined OS", async () => {
    const f = makeFetch().on("POST", "/v1/sessions", {
      json: {
        ...READY,
        device: { ...(READY as { device: object }).device, os: "recamagined" },
      },
    });
    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    const s = await c.createSession();
    await expect(s.device.inference.start()).rejects.toThrow(/reCamaginedOS/);
  });
});

describe("error mapping", () => {
  it("401 -> AuthenticationError", async () => {
    const f = makeFetch().on("GET", "/v1/sessions/sess_x", { status: 401 });
    const c = new EdgeLensClient({ apiKey: "bad", fetch: f.fetch });
    await expect(c.getSession("sess_x")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("404 -> SessionError", async () => {
    const f = makeFetch().on("GET", "/v1/sessions/sess_x", { status: 404 });
    const c = new EdgeLensClient({ apiKey: "k", fetch: f.fetch });
    await expect(c.getSession("sess_x")).rejects.toBeInstanceOf(SessionError);
  });
});

describe("retry policy", () => {
  it("retries idempotent GET on 503", async () => {
    let hits = 0;
    const f = makeFetch().on("GET", "/v1/sessions/sess_r", () => {
      hits++;
      if (hits < 3) return { status: 503 };
      return { json: { id: "sess_r", status: "ready" } };
    });
    const c = new EdgeLensClient({
      apiKey: "k",
      fetch: f.fetch,
      retryPolicy: new RetryPolicy({ maxAttempts: 4, baseDelayMs: 1, maxDelayMs: 5 }),
    });
    const s = await c.getSession("sess_r");
    expect(s.id).toBe("sess_r");
    expect(hits).toBe(3);
  });

  it("does NOT retry POST on 503 by default", async () => {
    let hits = 0;
    const f = makeFetch().on("POST", "/v1/sessions", () => {
      hits++;
      return { status: 503, body: "down" };
    });
    const c = new EdgeLensClient({
      apiKey: "k",
      fetch: f.fetch,
      retryPolicy: new RetryPolicy({ maxAttempts: 5, baseDelayMs: 1, maxDelayMs: 5 }),
    });
    await expect(c.createSession()).rejects.toThrow();
    expect(hits).toBe(1);
  });
});
