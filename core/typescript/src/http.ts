/**
 * Internal HTTP client — fetch-based, with the same retry semantics as
 * the Python SDK's `_http.HTTPClient`:
 *
 * - Retries on transport errors and {429, 502, 503, 504}
 * - Idempotent methods only by default (GET / DELETE / HEAD / OPTIONS)
 * - Decorrelated exponential backoff with jitter
 * - Honors `Retry-After` headers on 429 / 503
 * - Bearer-token auth
 * - Streaming reads via async iterator
 *
 * Uses the global `fetch` from Node 18+ / browsers — zero extra runtime
 * deps.
 */

import {
  AuthenticationError,
  EdgeLensError,
  SessionError,
} from "./errors.js";

export const DEFAULT_BASE_URL = "https://api.edgelens.ai";
export const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * exec and inference results hold the request open for the requested time;
 * the api adds its own 15 s upstream margin, so the client waits longer still.
 */
export const OP_READ_MARGIN_S = 30;

/**
 * Request timeout for a call the api holds open for `opSeconds`. Never
 * lower than the client's configured timeout.
 */
export function opTimeoutMs(clientTimeoutMs: number, opSeconds: number): number {
  return Math.max(clientTimeoutMs, (opSeconds + OP_READ_MARGIN_S) * 1000);
}

const DEFAULT_RETRY_METHODS = new Set(["GET", "DELETE", "HEAD", "OPTIONS"]);
const DEFAULT_RETRY_STATUSES = new Set([429, 502, 503, 504]);
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_BASE_DELAY_MS = 500;
const DEFAULT_MAX_DELAY_MS = 30_000;

export interface RetryPolicyOptions {
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  retryStatuses?: Iterable<number>;
  retryMethods?: Iterable<string>;
}

export class RetryPolicy {
  readonly maxAttempts: number;
  readonly baseDelayMs: number;
  readonly maxDelayMs: number;
  readonly retryStatuses: Set<number>;
  readonly retryMethods: Set<string>;

  constructor(opts: RetryPolicyOptions = {}) {
    this.maxAttempts = Math.max(1, Math.floor(opts.maxAttempts ?? DEFAULT_MAX_RETRIES));
    this.baseDelayMs = opts.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
    this.maxDelayMs = opts.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
    this.retryStatuses = new Set(opts.retryStatuses ?? DEFAULT_RETRY_STATUSES);
    this.retryMethods = new Set(
      Array.from(opts.retryMethods ?? DEFAULT_RETRY_METHODS, (m) => m.toUpperCase()),
    );
  }

  shouldRetry(method: string, status: number | null, attempt: number): boolean {
    if (attempt + 1 >= this.maxAttempts) return false;
    if (!this.retryMethods.has(method.toUpperCase())) return false;
    if (status === null) return true;
    return this.retryStatuses.has(status);
  }

  delayMs(attempt: number, retryAfterSec: number | null = null): number {
    if (retryAfterSec !== null && retryAfterSec > 0) {
      return Math.min(retryAfterSec * 1000, this.maxDelayMs);
    }
    const cap = Math.min(this.baseDelayMs * 2 ** attempt, this.maxDelayMs);
    return this.baseDelayMs + Math.random() * (cap - this.baseDelayMs);
  }
}

export interface HTTPClientOptions {
  apiKey: string;
  baseUrl?: string;
  timeoutMs?: number;
  retryPolicy?: RetryPolicy;
  userAgent?: string;
  /** Inject a custom fetch (tests, proxy, etc.). Defaults to global fetch. */
  fetch?: typeof fetch;
  /**
   * Allow non-https baseUrl. Default
   * false. Setting this true permits http:// + private-IP literals so
   * the SDK can talk to a local dev instance of the EdgeLens API. Never enable in prod.
   */
  allowInsecureBaseUrl?: boolean;
}


/**
 * Mirrors the Python SDK's base URL validation.
 *
 * Reject base URLs that would exfiltrate the Bearer token:
 * - non-http(s) schemes (file://, gopher://, ...)
 * - http:// unless allowInsecure=true
 * - loopback / RFC1918 / link-local hostnames (incl. cloud IMDS)
 */
function validateBaseUrl(url: string, allowInsecure: boolean): string {
  if (!url) {
    throw new EdgeLensError("baseUrl is empty");
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch (e) {
    throw new EdgeLensError(`baseUrl is not a valid URL: ${url}`);
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new EdgeLensError(
      `baseUrl scheme ${parsed.protocol} not allowed (use http or https)`,
    );
  }
  if (parsed.protocol === "http:" && !allowInsecure) {
    throw new EdgeLensError(
      "baseUrl uses http:// — Bearer token would be sent in cleartext. " +
        "Pass allowInsecureBaseUrl: true if this is a local dev loop.",
    );
  }
  const host = parsed.hostname;
  if (!host) {
    throw new EdgeLensError("baseUrl is missing a host");
  }
  // Reject private + cloud-metadata addresses.
  if (
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "0.0.0.0" ||
    host === "169.254.169.254" ||
    host.startsWith("10.") ||
    host.startsWith("192.168.") ||
    /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(host) ||
    host.startsWith("169.254.") ||
    host === "::1" ||
    host.toLowerCase().startsWith("[::ffff:")
  ) {
    if (!allowInsecure) {
      throw new EdgeLensError(
        `baseUrl host ${host} is private/loopback/link-local — refusing ` +
          "to send Bearer token there. Pass allowInsecureBaseUrl: true to override.",
      );
    }
  }
  return url.replace(/\/+$/, "");
}

interface RequestOptions {
  json?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
  body?: BodyInit;
  /** Override headers (Content-Type set automatically when json/body given). */
  headers?: Record<string, string>;
  /** Per-request timeout; defaults to the client's configured timeout. */
  timeoutMs?: number;
}

function parseRetryAfter(headers: Headers): number | null {
  const raw = headers.get("retry-after");
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function buildSearch(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return "";
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue;
    usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export class HTTPClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly clientTimeoutMs: number;
  private readonly retry: RetryPolicy;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: HTTPClientOptions) {
    this.apiKey = opts.apiKey;
    // Scheme + host validation.
    this.baseUrl = validateBaseUrl(
      opts.baseUrl ?? DEFAULT_BASE_URL,
      opts.allowInsecureBaseUrl ?? false,
    );
    this.clientTimeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.retry = opts.retryPolicy ?? new RetryPolicy();
    this.userAgent = opts.userAgent ?? "edgelens-typescript/0.1.0";
    this.fetchImpl = opts.fetch ?? fetch.bind(globalThis);
  }

  /** The client's configured per-request timeout. */
  get timeoutMs(): number {
    return this.clientTimeoutMs;
  }

  async request<T = unknown>(
    method: string,
    path: string,
    opts: RequestOptions = {},
  ): Promise<T> {
    const response = await this.sendWithRetry(method, path, opts);
    return this.handleResponse<T>(response, path);
  }

  private async sendWithRetry(
    method: string,
    path: string,
    opts: RequestOptions,
  ): Promise<Response> {
    let attempt = 0;
    const url = `${this.baseUrl}${path}${buildSearch(opts.params)}`;
    while (true) {
      const headers: Record<string, string> = {
        Authorization: `Bearer ${this.apiKey}`,
        "User-Agent": this.userAgent,
        ...(opts.headers ?? {}),
      };
      let body: BodyInit | undefined = opts.body;
      if (opts.json !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(opts.json);
      }

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? this.clientTimeoutMs);
      let response: Response;
      try {
        response = await this.fetchImpl(url, {
          method,
          headers,
          body,
          signal: controller.signal,
          // Never follow redirects
          // automatically. The Bearer header is in `headers` above
          // and would replay against an attacker-controlled redirect
          // target on a runtime that doesn't strip cross-origin auth.
          redirect: "manual",
        });
        // A 3xx with redirect:manual surfaces as a synthetic 'opaqueredirect'
        // or as the 3xx itself depending on the runtime. Treat any 3xx as
        // a refusal.
        if (response.status >= 300 && response.status < 400) {
          clearTimeout(timer);
          throw new EdgeLensError(
            `Refusing to follow redirect from ${url} (status ${response.status}). ` +
              "Cross-origin redirects would replay the Bearer token.",
          );
        }
      } catch (e) {
        clearTimeout(timer);
        if (!this.retry.shouldRetry(method, null, attempt)) {
          throw new EdgeLensError(
            `HTTP transport error for ${method} ${path}: ${(e as Error).message}`,
          );
        }
        await sleep(this.retry.delayMs(attempt));
        attempt++;
        continue;
      }
      clearTimeout(timer);

      if (!this.retry.shouldRetry(method, response.status, attempt)) {
        return response;
      }
      await sleep(this.retry.delayMs(attempt, parseRetryAfter(response.headers)));
      attempt++;
    }
  }

  private async handleResponse<T>(response: Response, path: string): Promise<T> {
    if (response.status === 401) {
      throw new AuthenticationError("Invalid or expired API key");
    }
    if (response.status === 403) {
      throw new AuthenticationError(
        `API key does not have permission: ${await readErrorMessage(response)}`,
      );
    }
    if (response.status === 404) {
      throw new SessionError(`Resource not found: ${path}`);
    }
    if (response.status >= 400) {
      throw new EdgeLensError(
        `API error ${response.status}: ${await readErrorMessage(response)}`,
      );
    }
    const ct = response.headers.get("content-type") ?? "";
    if (ct.startsWith("application/json")) {
      return (await response.json()) as T;
    }
    // Non-JSON bodies fall through to the caller as bytes — same as Python.
    return (await response.arrayBuffer()) as unknown as T;
  }

  get<T = unknown>(path: string, params?: RequestOptions["params"]): Promise<T> {
    return this.request<T>("GET", path, { params });
  }

  post<T = unknown>(
    path: string,
    opts: Pick<RequestOptions, "json" | "body" | "headers" | "params" | "timeoutMs"> = {},
  ): Promise<T> {
    return this.request<T>("POST", path, opts);
  }

  delete<T = unknown>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  /**
   * Stream raw bytes from an endpoint. No retries — once the body
   * starts arriving, downstream consumers may have already moved
   * state forward.
   */
  async *stream(
    method: string,
    path: string,
    params?: RequestOptions["params"],
  ): AsyncGenerator<Uint8Array, void, void> {
    const url = `${this.baseUrl}${path}${buildSearch(params)}`;
    const response = await this.fetchImpl(url, {
      method,
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "User-Agent": this.userAgent,
      },
      // Same as the request path.
      redirect: "manual",
    });
    if (response.status >= 300 && response.status < 400) {
      throw new EdgeLensError(
        `Refusing to follow redirect from ${url} (status ${response.status}) — ` +
          "Bearer token would replay.",
      );
    }
    await this.raiseForStatusHeadersOnly(response, path);
    if (!response.body) {
      throw new EdgeLensError("Stream response had no body");
    }
    const reader = response.body.getReader();
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) yield value;
      }
    } finally {
      reader.releaseLock();
    }
  }

  private async raiseForStatusHeadersOnly(response: Response, path: string): Promise<void> {
    if (response.status === 401) {
      throw new AuthenticationError("Invalid or expired API key");
    }
    if (response.status === 403) {
      throw new AuthenticationError("API key does not have permission");
    }
    if (response.status === 404) {
      throw new SessionError(`Resource not found: ${path}`);
    }
    if (response.status >= 400) {
      throw new EdgeLensError(`API error ${response.status}`);
    }
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const data = (await response.clone().json()) as Record<string, unknown>;
    const msg = (data.message ?? data.error ?? data.detail) as string | undefined;
    if (msg) return msg;
  } catch {
    /* fall through */
  }
  try {
    return await response.text();
  } catch {
    return response.statusText;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
