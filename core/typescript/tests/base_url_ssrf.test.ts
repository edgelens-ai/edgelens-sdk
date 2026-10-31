/**
 * baseUrl scheme + host validation.
 * redirect:'manual' on every fetch.
 */
import { readFileSync } from "node:fs";

import { afterEach, describe, expect, it, vi } from "vitest";

import { EdgeLensClient, EdgeLensError, classifyHost } from "../src/index.js";

/** Shared with the Python suite, so both clients refuse the same hosts. */
const HOSTS = JSON.parse(
  readFileSync(new URL("../../testdata/base_url_hosts.json", import.meta.url), "utf8"),
) as { refused: string[]; private: string[]; public: string[] };

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("baseUrl validation", () => {
  it("refuses http:// by default", () => {
    expect(() =>
      new EdgeLensClient({ apiKey: "k", baseUrl: "http://api.edgelens.ai" }),
    ).toThrow(/http:\/\//);
  });

  it("allows http:// when allowInsecureBaseUrl is true", () => {
    new EdgeLensClient({
      apiKey: "k",
      baseUrl: "http://api.edgelens.ai",
      allowInsecureBaseUrl: true,
    });
  });

  it("needs both overrides for an http://localhost dev loop", () => {
    expect(
      () =>
        new EdgeLensClient({
          apiKey: "k",
          baseUrl: "http://localhost:8000",
          allowInsecureBaseUrl: true,
        }),
    ).toThrow(/private\/loopback/);
    new EdgeLensClient({
      apiKey: "k",
      baseUrl: "http://localhost:8000",
      allowInsecureBaseUrl: true,
      allowPrivateBaseUrl: true,
    });
  });

  it.each(["http://169.254.169.254", "http://10.0.0.1", "http://[fd00:ec2::254]"])(
    "allowInsecureBaseUrl alone does not relax the host check: %s",
    (url) => {
      expect(
        () => new EdgeLensClient({ apiKey: "k", baseUrl: url, allowInsecureBaseUrl: true }),
      ).toThrow(/private|reserved/);
    },
  );

  it("refuses non-http schemes", () => {
    for (const url of ["file:///etc/passwd", "gopher://evil", "ws://x"]) {
      expect(() =>
        new EdgeLensClient({ apiKey: "k", baseUrl: url }),
      ).toThrow(/scheme/);
    }
  });

  it("accepts public https URLs", () => {
    new EdgeLensClient({ apiKey: "k", baseUrl: "https://api.edgelens.ai" });
  });
});

describe("shared host table", () => {
  it.each(HOSTS.refused)("refuses %s even with the private override", (host) => {
    expect(
      () =>
        new EdgeLensClient({
          apiKey: "k",
          baseUrl: `https://${host}/`,
          allowPrivateBaseUrl: true,
        }),
    ).toThrow(/link-local\/reserved/);
  });

  it.each(HOSTS.private)("refuses %s unless the private override is set", (host) => {
    expect(
      () => new EdgeLensClient({ apiKey: "k", baseUrl: `https://${host}/` }),
    ).toThrow(/private\/loopback/);
    new EdgeLensClient({ apiKey: "k", baseUrl: `https://${host}/`, allowPrivateBaseUrl: true });
  });

  it.each(HOSTS.public)("accepts %s", (host) => {
    new EdgeLensClient({ apiKey: "k", baseUrl: `https://${host}/` });
  });
});

describe("private override", () => {
  it.each(["1", "true", "YES", " on "])(
    "EDGELENS_ALLOW_PRIVATE_BASE_URL=%j allows a private host",
    (value) => {
      vi.stubEnv("EDGELENS_ALLOW_PRIVATE_BASE_URL", value);
      new EdgeLensClient({ apiKey: "k", baseUrl: "https://10.0.0.5:8000" });
    },
  );

  it.each(["", "0", "false", "no"])("EDGELENS_ALLOW_PRIVATE_BASE_URL=%j does not", (value) => {
    vi.stubEnv("EDGELENS_ALLOW_PRIVATE_BASE_URL", value);
    expect(
      () => new EdgeLensClient({ apiKey: "k", baseUrl: "https://10.0.0.5:8000" }),
    ).toThrow(/private\/loopback/);
  });

  it("an explicit allowPrivateBaseUrl: false wins over the env", () => {
    vi.stubEnv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1");
    expect(
      () =>
        new EdgeLensClient({
          apiKey: "k",
          baseUrl: "https://127.0.0.1",
          allowPrivateBaseUrl: false,
        }),
    ).toThrow(/private\/loopback/);
  });

  it("never relaxes cloud metadata", () => {
    vi.stubEnv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1");
    for (const host of ["169.254.169.254", "[fd00:ec2::254]", "[::ffff:169.254.169.254]"]) {
      expect(
        () => new EdgeLensClient({ apiKey: "k", baseUrl: `https://${host}` }),
      ).toThrow(/link-local\/reserved/);
    }
  });
});

describe("classifyHost", () => {
  it("strips the brackets WHATWG URL keeps on IPv6 hostnames", () => {
    expect(new URL("https://[::1]/").hostname).toBe("[::1]");
    expect(classifyHost("[fd00::1]")).toBe("private");
    expect(classifyHost("fd00::1")).toBe("private");
  });

  it("judges an IPv4-mapped address as its IPv4 address", () => {
    expect(classifyHost("[::ffff:7f00:1]")).toBe("private");
    expect(classifyHost("[::ffff:808:808]")).toBe("public");
  });
});

describe("redirect:'manual'", () => {
  it("aborts on a 3xx with EdgeLensError instead of replaying the Bearer", async () => {
    const fakeFetch: typeof fetch = async () =>
      new Response(null, {
        status: 302,
        headers: { location: "https://evil.example.com/sink" },
      });

    const c = new EdgeLensClient({
      apiKey: "k",
      baseUrl: "https://api.edgelens.ai",
      fetch: fakeFetch,
    });
    await expect(c.getSession("sess_x")).rejects.toThrow(EdgeLensError);
  });
});
