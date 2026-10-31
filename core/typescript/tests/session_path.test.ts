/**
 * A session id is one opaque path segment. An id holding `/`, `..`, `?`
 * or `#` must not reach another route on the same host with the key
 * attached.
 */
import { describe, expect, it } from "vitest";

import { EdgeLensClient, EdgeLensError } from "../src/index.js";
import { sessionPath } from "../src/http.js";
import { stripTrailingSlashes } from "../src/baseurl.js";

const BASE = "https://api.edgelens.ai";

function recordingClient(id: string): { client: EdgeLensClient; urls: string[] } {
  const urls: string[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    urls.push(typeof input === "string" || input instanceof URL ? String(input) : input.url);
    const body = {
      id,
      status: "ready",
      device: {
        mac: "aa:bb:cc:00:00:01",
        host: "192.0.2.42",
        ssh_port: 30007,
        ssh_user: "recamera",
        ssh_password: "x".repeat(24),
        os: "stock-os",
      },
      stdout: "",
      stderr: "",
      exit_code: 0,
    };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return { client: new EdgeLensClient({ apiKey: "k", fetch: fetchImpl }), urls };
}

const CASES: [string, string][] = [
  ["../accounts/me/keys", "..%2Faccounts%2Fme%2Fkeys"],
  ["sess/../../admin", "sess%2F..%2F..%2Fadmin"],
  ["sess?admin=1", "sess%3Fadmin%3D1"],
  ["sess#frag", "sess%23frag"],
  ["sess%2F", "sess%252F"],
];

describe("session id in request paths", () => {
  it.each(CASES)("getSession sends %s as one encoded segment", async (id, encoded) => {
    const { client, urls } = recordingClient(id);
    await client.getSession(id);
    expect(urls).toEqual([`${BASE}/v1/sessions/${encoded}`]);
    const u = new URL(urls[0]!);
    expect(u.pathname).toBe(`/v1/sessions/${encoded}`);
    expect(u.search).toBe("");
    expect(u.hash).toBe("");
  });

  it.each(CASES)("release, refresh and exec send %s encoded", async (id, encoded) => {
    const { client, urls } = recordingClient(id);
    const s = await client.getSession(id);
    await s.refresh();
    await s.device.exec("true");
    await s.release();
    expect(urls.slice(1)).toEqual([
      `${BASE}/v1/sessions/${encoded}`,
      `${BASE}/v1/sessions/${encoded}/exec`,
      `${BASE}/v1/sessions/${encoded}`,
    ]);
  });

  it.each(["", ".", ".."])("refuses the id %j before sending anything", async (id) => {
    const { client, urls } = recordingClient(id);
    await expect(client.getSession(id)).rejects.toThrow(EdgeLensError);
    expect(urls).toEqual([]);
  });

  it("leaves an ordinary id unchanged", () => {
    expect(sessionPath("sess_abc123", "/info")).toBe("/v1/sessions/sess_abc123/info");
  });
});

describe("baseUrl trailing slashes", () => {
  it("strips a long run of slashes in linear time", () => {
    const run = "/".repeat(200_000);
    const start = performance.now();
    expect(stripTrailingSlashes(`https://api.edgelens.ai${run}`)).toBe("https://api.edgelens.ai");
    expect(stripTrailingSlashes(`${run}x`)).toBe(`${run}x`);
    expect(performance.now() - start).toBeLessThan(500);
  });

  it("is applied to the configured baseUrl", async () => {
    const urls: string[] = [];
    const fetchImpl: typeof fetch = async (input) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ id: "s", status: "ready" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };
    const client = new EdgeLensClient({
      apiKey: "k",
      baseUrl: `${BASE}${"/".repeat(5000)}`,
      fetch: fetchImpl,
    });
    await client.getSession("s");
    expect(urls).toEqual([`${BASE}/v1/sessions/s`]);
  });
});
