/**
 * baseUrl scheme + host validation.
 * redirect:'manual' on every fetch.
 */
import { describe, expect, it } from "vitest";

import { EdgeLensClient, EdgeLensError } from "../src/index.js";


describe("baseUrl validation", () => {
  it("refuses http:// by default", () => {
    expect(() =>
      new EdgeLensClient({ apiKey: "k", baseUrl: "http://api.edgelens.ai" }),
    ).toThrow(/http:\/\//);
  });

  it("allows http:// when allowInsecureBaseUrl is true", () => {
    new EdgeLensClient({
      apiKey: "k",
      baseUrl: "http://localhost:8000",
      allowInsecureBaseUrl: true,
    });
  });

  it("refuses non-http schemes", () => {
    for (const url of ["file:///etc/passwd", "gopher://evil", "ws://x"]) {
      expect(() =>
        new EdgeLensClient({ apiKey: "k", baseUrl: url }),
      ).toThrow(/scheme/);
    }
  });

  it.each([
    "127.0.0.1",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "169.254.169.254",
    "0.0.0.0",
  ])("refuses private/loopback IP literal %s", (host) => {
    expect(() =>
      new EdgeLensClient({ apiKey: "k", baseUrl: `https://${host}` }),
    ).toThrow(/private|loopback/);
  });

  it("accepts public https URLs", () => {
    new EdgeLensClient({ apiKey: "k", baseUrl: "https://api.edgelens.ai" });
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
