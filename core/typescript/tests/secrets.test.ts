import { inspect, format } from "node:util";

import { describe, expect, it } from "vitest";

import { EdgeLensClient } from "../src/index.js";
import { makeFetch } from "./helpers.js";

const PASSWORD = "pw-" + "q".repeat(21);
const API_KEY = "el_test_" + "k".repeat(24);

async function readySession() {
  const f = makeFetch().on("GET", "/v1/sessions/sess_s", {
    json: {
      id: "sess_s",
      status: "ready",
      device: {
        mac: "aa:bb:cc:00:00:01",
        host: "192.0.2.42",
        ssh_port: 30007,
        ssh_user: "recamera",
        ssh_password: PASSWORD,
        os: "stock-os",
      },
    },
  });
  const client = new EdgeLensClient({ apiKey: API_KEY, fetch: f.fetch });
  return { client, session: await client.getSession("sess_s") };
}

// Every route a value takes into a log line or a report attachment.
function renderings(value: unknown): string[] {
  return [
    inspect(value, { depth: Infinity }),
    format("%o", value),
    format("%O", value),
    format("%j", value),
    JSON.stringify(value) ?? "",
    JSON.stringify({ ...(value as object) }) ?? "",
  ];
}

describe("secrets stay out of printed and serialised objects", () => {
  it("a session and its device never print the SSH password or the API key", async () => {
    const { session } = await readySession();
    for (const value of [session, session.device]) {
      for (const text of renderings(value)) {
        expect(text).not.toContain(PASSWORD);
        expect(text).not.toContain(API_KEY);
      }
    }
    expect(inspect(session.device, { depth: Infinity })).toContain("192.0.2.42");
  });

  it("ssh() credentials omit the password when printed but keep it readable", async () => {
    const { session } = await readySession();
    const creds = session.device.ssh();
    for (const text of renderings(creds)) {
      expect(text).not.toContain(PASSWORD);
    }
    expect(creds.password).toBe(PASSWORD);
    expect(Object.keys(creds)).toEqual(["user", "host", "port"]);
    expect(JSON.parse(JSON.stringify(creds))).toEqual({
      user: "recamera",
      host: "192.0.2.42",
      port: 30007,
    });
  });

  it("the password cannot be overwritten through the credentials object", async () => {
    const { session } = await readySession();
    const creds = session.device.ssh();
    expect(() => {
      (creds as { password: string }).password = "changed";
    }).toThrow(TypeError);
    expect(session.device.ssh().password).toBe(PASSWORD);
  });

  it("a client never prints its API key", async () => {
    const { client } = await readySession();
    for (const text of renderings(client)) {
      expect(text).not.toContain(API_KEY);
    }
  });

  it("the API key still authenticates requests", async () => {
    const f = makeFetch().on("GET", "/v1/sessions/sess_a", {
      json: { id: "sess_a", status: "flashing" },
    });
    const client = new EdgeLensClient({ apiKey: API_KEY, fetch: f.fetch });
    await client.getSession("sess_a");
    expect(f.calls[0]?.headers.authorization).toBe(`Bearer ${API_KEY}`);
  });
});
