/**
 * baseUrl validation. The same denylist as the Python SDK's
 * `edgelens._http._validate_base_url`; both read their ranges from the
 * tables below, and both suites run the shared cases in
 * `core/testdata/base_url_hosts.json`.
 *
 * Two independent overrides:
 * - `allowInsecureBaseUrl` permits http://. It does not relax the host check.
 * - `allowPrivateBaseUrl` (or `EDGELENS_ALLOW_PRIVATE_BASE_URL=1`) permits
 *   loopback, private and shared (100.64.0.0/10) addresses and `localhost`,
 *   for a server you control, such as a local test server. Link-local, multicast, unspecified,
 *   reserved and cloud metadata addresses are refused regardless.
 *
 * The check is on the host literal only: a DNS name that resolves to a
 * private address is not caught here.
 */

import { EdgeLensError } from "./errors.js";

export type HostClass = "public" | "private" | "refused";

interface Net {
  base: bigint;
  shift: bigint;
}

function net(cidr: string): Net {
  const [addr, len] = cidr.split("/") as [string, string];
  const v4 = parseIPv4(addr);
  const bits = v4 !== null ? 32 : 128;
  const base = v4 ?? parseIPv6(addr);
  if (base === null) throw new Error(`bad network ${cidr}`);
  const shift = BigInt(bits - Number(len));
  return { base: base >> shift, shift };
}

function inAny(ip: bigint, nets: Net[]): boolean {
  return nets.some((n) => ip >> n.shift === n.base);
}

// Refused even with the private override: link-local, multicast,
// unspecified, reserved, and the IPv6 instance metadata address.
const V4_REFUSED = ["169.254.0.0/16", "224.0.0.0/4", "0.0.0.0/32", "240.0.0.0/4"].map(net);
const V6_REFUSED = [
  "fe80::/10", "ff00::/8", "::/128", "fd00:ec2::254/128",
  "::/8", "100::/8", "200::/7", "400::/6", "800::/5", "1000::/4", "4000::/3",
  "6000::/3", "8000::/3", "a000::/3", "c000::/3", "e000::/4", "f000::/5",
  "f800::/6", "fe00::/9",
].map(net);

// Refused unless the private override is set: loopback, private-use,
// shared address space and the special-purpose blocks.
const V4_PRIVATE = [
  "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "172.16.0.0/12",
  "192.0.0.0/24", "192.0.0.170/31", "192.0.2.0/24", "192.168.0.0/16",
  "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
].map(net);
const V4_PRIVATE_EXCEPT = ["192.0.0.9/32", "192.0.0.10/32"].map(net);
const V6_PRIVATE = [
  "::1/128", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32",
  "2002::/16", "3fff::/20", "fc00::/7",
].map(net);
const V6_PRIVATE_EXCEPT = [
  "2001:1::1/128", "2001:1::2/128", "2001:3::/32", "2001:4:112::/48",
  "2001:20::/28", "2001:30::/28",
].map(net);

const V4_MAPPED = net("::ffff:0:0/96");

function parseIPv4(s: string): bigint | null {
  const parts = s.split(".");
  if (parts.length !== 4) return null;
  let v = 0n;
  for (const p of parts) {
    if (!/^(0|[1-9]\d{0,2})$/.test(p)) return null;
    const n = Number(p);
    if (n > 255) return null;
    v = (v << 8n) | BigInt(n);
  }
  return v;
}

function parseIPv6(s: string): bigint | null {
  let text = s;
  const lastColon = text.lastIndexOf(":");
  if (lastColon < 0) return null;
  const tail = text.slice(lastColon + 1);
  if (tail.includes(".")) {
    const v4 = parseIPv4(tail);
    if (v4 === null) return null;
    text = `${text.slice(0, lastColon + 1)}${(v4 >> 16n).toString(16)}:${(v4 & 0xffffn).toString(16)}`;
  }
  const halves = text.split("::");
  if (halves.length > 2) return null;
  const groups = (part: string): string[] => (part === "" ? [] : part.split(":"));
  const left = groups(halves[0] ?? "");
  const right = halves.length === 2 ? groups(halves[1] ?? "") : [];
  const fill = 8 - left.length - right.length;
  if (halves.length === 1 ? fill !== 0 : fill < 1) return null;
  let v = 0n;
  for (const g of [...left, ...Array<string>(fill).fill("0"), ...right]) {
    if (!/^[0-9a-f]{1,4}$/.test(g)) return null;
    v = (v << 16n) | BigInt(parseInt(g, 16));
  }
  return v;
}

function classifyV4(ip: bigint): HostClass {
  if (inAny(ip, V4_REFUSED)) return "refused";
  if (inAny(ip, V4_PRIVATE) && !inAny(ip, V4_PRIVATE_EXCEPT)) return "private";
  return "public";
}

/**
 * Classify a URL hostname as WHATWG `URL.hostname` returns it: IPv6 in
 * brackets, IPv4 already normalised from shorthand forms.
 */
export function classifyHost(hostname: string): HostClass {
  let host = hostname.toLowerCase();
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (host.endsWith(".")) host = host.slice(0, -1);
  if (host === "localhost" || host.endsWith(".localhost")) return "private";

  const v4 = parseIPv4(host);
  if (v4 !== null) return classifyV4(v4);

  const v6 = parseIPv6(host);
  if (v6 === null) return "public";
  if (inAny(v6, [V4_MAPPED])) return classifyV4(v6 & 0xffffffffn);
  if (inAny(v6, V6_REFUSED)) return "refused";
  if (inAny(v6, V6_PRIVATE) && !inAny(v6, V6_PRIVATE_EXCEPT)) return "private";
  return "public";
}

const TRUTHY = new Set(["1", "true", "yes", "on"]);

/** `EDGELENS_ALLOW_PRIVATE_BASE_URL`, read the way the Python SDK reads it. */
export function allowPrivateFromEnv(): boolean {
  const env = typeof process !== "undefined" ? process.env : undefined;
  return TRUTHY.has((env?.EDGELENS_ALLOW_PRIVATE_BASE_URL ?? "").trim().toLowerCase());
}

export interface BaseUrlPolicy {
  allowInsecure: boolean;
  allowPrivate: boolean;
}

/** Returns the URL without trailing slashes, or throws EdgeLensError. */
export function validateBaseUrl(url: string, policy: BaseUrlPolicy): string {
  if (!url) {
    throw new EdgeLensError("baseUrl is empty");
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new EdgeLensError(`baseUrl is not a valid URL: ${url}`);
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new EdgeLensError(
      `baseUrl scheme ${parsed.protocol} not allowed (use http or https)`,
    );
  }
  if (parsed.protocol === "http:" && !policy.allowInsecure) {
    throw new EdgeLensError(
      "baseUrl uses http://, so the Bearer token would be sent in cleartext. " +
        "Pass allowInsecureBaseUrl: true if this is a local dev loop.",
    );
  }
  const host = parsed.hostname;
  if (!host) {
    throw new EdgeLensError("baseUrl is missing a host");
  }
  const cls = classifyHost(host);
  if (cls === "refused") {
    throw new EdgeLensError(
      `baseUrl host ${host} is a link-local/reserved address; refusing to ` +
        "send the Bearer token there.",
    );
  }
  if (cls === "private" && !policy.allowPrivate) {
    throw new EdgeLensError(
      `baseUrl host ${host} is a private/loopback address. If this is a ` +
        "server you control, such as a local test server, pass allowPrivateBaseUrl: true " +
        "or set EDGELENS_ALLOW_PRIVATE_BASE_URL=1.",
    );
  }
  return stripTrailingSlashes(url);
}

/** Linear in the length of `s`, whatever it holds. */
export function stripTrailingSlashes(s: string): string {
  let end = s.length;
  while (end > 0 && s.charCodeAt(end - 1) === 0x2f) end--;
  return s.slice(0, end);
}
