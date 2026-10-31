/**
 * Internal HTTP client — fetch-based, with the same retry semantics as
 * the Python SDK's `_http.HTTPClient`:
 *
 * - Retries on transport errors and {429, 502, 503, 504}
 * - Idempotent methods only by default (GET / DELETE / HEAD / OPTIONS)
 * - Decorrelated exponential backoff with jitter
 * - Honors `Retry-After` headers on 429 / 503
 * - Bearer-token auth
 * - Streaming reads via async iterator, with byte, duration and idle caps
 * - A per-request timeout that covers the body as well as the headers, and
 *   a cap on how much of a body is buffered
 *
 * Uses the global `fetch` from Node 18+ / browsers — zero extra runtime
 * deps.
 */

import { allowPrivateFromEnv, validateBaseUrl } from "./baseurl.js";
import {
  AuthenticationError,
  EdgeLensError,
  EdgeLensTimeoutError,
  SessionError,
} from "./errors.js";
import { defineSecret } from "./secret.js";

/**
 * `/v1/sessions/<id><suffix>` with the id as one opaque path segment, so an
 * id holding `/`, `?` or `#` cannot reach another route. `.` and `..` are
 * refused: a URL parser resolves them as dot segments even when encoded.
 */
export function sessionPath(sessionId: string, suffix = ""): string {
  if (sessionId === "" || sessionId === "." || sessionId === "..") {
    throw new EdgeLensError(`invalid session id: ${JSON.stringify(sessionId)}`);
  }
  return `/v1/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

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

/** Largest response body `request()` will buffer. */
export const DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024;

/** `stream()` defaults, the same as the Python SDK's. */
export const DEFAULT_STREAM_MAX_BYTES = 1024 * 1024 * 1024;
export const DEFAULT_STREAM_MAX_DURATION_MS = 600_000;

/**
 * Error bodies are read up to this many bytes, and the server's message is
 * cut to MAX_ERROR_MESSAGE_CHARS characters in the thrown error.
 */
export const MAX_ERROR_BODY_BYTES = 64 * 1024;
export const MAX_ERROR_MESSAGE_CHARS = 512;

export interface HTTPClientOptions {
  apiKey: string;
  baseUrl?: string;
  /**
   * Per-request timeout in milliseconds. It covers the whole request:
   * connect, headers and reading the body.
   */
  timeoutMs?: number;
  retryPolicy?: RetryPolicy;
  userAgent?: string;
  /** Inject a custom fetch (tests, proxy, etc.). Defaults to global fetch. */
  fetch?: typeof fetch;
  /**
   * Allow an http:// baseUrl, for a local dev loop. Default false. This
   * does not relax the host check; see `allowPrivateBaseUrl`.
   */
  allowInsecureBaseUrl?: boolean;
  /**
   * Allow a loopback, private or shared-address baseUrl host, or
   * `localhost`, for a server you control such as a local test server. Defaults to the
   * `EDGELENS_ALLOW_PRIVATE_BASE_URL` environment variable (1/true/yes/on).
   * Link-local, reserved and cloud metadata addresses stay refused.
   */
  allowPrivateBaseUrl?: boolean;
  /** Largest response body to buffer. Default DEFAULT_MAX_RESPONSE_BYTES. */
  maxResponseBytes?: number;
}

/**
 * Caps for `stream()`. `null` disables a cap; an omitted field takes its
 * default.
 */
export interface StreamOptions {
  /** Total bytes across all chunks. Default 1 GiB. */
  maxBytes?: number | null;
  /** Wall-clock limit from the response headers on. Default 600 s. */
  maxDurationMs?: number | null;
  /**
   * Longest wait for the headers or for any single chunk. Defaults to the
   * client's timeoutMs.
   */
  idleTimeoutMs?: number | null;
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

type Attempt<T> = { done: true; value: T } | { done: false; delayMs: number };

export class HTTPClient {
  /** Non-enumerable, so printing or serialising a client omits the key. */
  declare private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly clientTimeoutMs: number;
  private readonly retry: RetryPolicy;
  private readonly userAgent: string;
  private readonly fetchImpl: typeof fetch;
  private readonly maxResponseBytes: number;

  constructor(opts: HTTPClientOptions) {
    defineSecret(this, "apiKey", opts.apiKey);
    this.baseUrl = validateBaseUrl(opts.baseUrl ?? DEFAULT_BASE_URL, {
      allowInsecure: opts.allowInsecureBaseUrl ?? false,
      allowPrivate: opts.allowPrivateBaseUrl ?? allowPrivateFromEnv(),
    });
    this.clientTimeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.retry = opts.retryPolicy ?? new RetryPolicy();
    this.userAgent = opts.userAgent ?? "edgelens-typescript/0.2.4";
    this.fetchImpl = opts.fetch ?? fetch.bind(globalThis);
    this.maxResponseBytes = opts.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES;
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
    const url = `${this.baseUrl}${path}${buildSearch(opts.params)}`;
    const timeoutMs = opts.timeoutMs ?? this.clientTimeoutMs;
    for (let attempt = 0; ; attempt++) {
      const result = await this.attempt<T>(method, url, path, opts, timeoutMs, attempt);
      if (result.done) return result.value;
      await sleep(result.delayMs);
    }
  }

  private headers(extra?: Record<string, string>): Record<string, string> {
    return {
      Authorization: `Bearer ${this.apiKey}`,
      "User-Agent": this.userAgent,
      ...(extra ?? {}),
    };
  }

  /**
   * One try. The timer runs from the start of the fetch until the body has
   * been read, so a server that sends headers and then stalls the body is
   * still bounded by `timeoutMs`.
   */
  private async attempt<T>(
    method: string,
    url: string,
    path: string,
    opts: RequestOptions,
    timeoutMs: number,
    attempt: number,
  ): Promise<Attempt<T>> {
    const headers = this.headers(opts.headers);
    let body: BodyInit | undefined = opts.body;
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.json);
    }

    const controller = new AbortController();
    const deadline = Date.now() + timeoutMs;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const timedOut = () =>
      new EdgeLensTimeoutError(`${method} ${path} did not complete within ${timeoutMs}ms`);
    try {
      let response: Response;
      try {
        response = await within(
          this.fetchImpl(url, {
            method,
            headers,
            body,
            signal: controller.signal,
            // Never follow redirects automatically. The Bearer header
            // would replay against the redirect target on a runtime that
            // does not strip cross-origin auth.
            redirect: "manual",
          }),
          deadline - Date.now(),
          timedOut,
        );
      } catch (e) {
        if (!this.retry.shouldRetry(method, null, attempt)) {
          throw new EdgeLensError(
            `HTTP transport error for ${method} ${path}: ${(e as Error).message}`,
          );
        }
        return { done: false, delayMs: this.retry.delayMs(attempt) };
      }
      // A 3xx with redirect:manual surfaces as a synthetic 'opaqueredirect'
      // or as the 3xx itself depending on the runtime. Treat any 3xx as
      // a refusal.
      if (response.status >= 300 && response.status < 400) {
        discard(response);
        throw new EdgeLensError(
          `Refusing to follow redirect from ${url} (status ${response.status}). ` +
            "Cross-origin redirects would replay the Bearer token.",
        );
      }
      if (this.retry.shouldRetry(method, response.status, attempt)) {
        discard(response);
        return {
          done: false,
          delayMs: this.retry.delayMs(attempt, parseRetryAfter(response.headers)),
        };
      }
      const value = await this.handleResponse<T>(response, path, deadline, controller, timedOut);
      return { done: true, value };
    } finally {
      clearTimeout(timer);
    }
  }

  private async handleResponse<T>(
    response: Response,
    path: string,
    deadline: number,
    controller: AbortController,
    timedOut: () => Error,
  ): Promise<T> {
    if (response.status === 401) {
      discard(response);
      throw new AuthenticationError("Invalid or expired API key");
    }
    if (response.status === 403) {
      throw new AuthenticationError(
        `API key does not have permission: ${await readErrorMessage(response, deadline)}`,
      );
    }
    if (response.status === 404) {
      discard(response);
      throw new SessionError(`Resource not found: ${path}`);
    }
    if (response.status >= 400) {
      throw new EdgeLensError(
        `API error ${response.status}: ${await readErrorMessage(response, deadline)}`,
      );
    }
    const limit = this.maxResponseBytes;
    const bytes = await readBody(response, {
      deadline,
      limit,
      onTimeout: timedOut,
      onOverflow: (total) =>
        new EdgeLensError(
          `response body for ${path} exceeded maxResponseBytes (${limit}); ` +
            `aborted after ${total} bytes`,
        ),
      abort: () => controller.abort(),
    });
    const ct = response.headers.get("content-type") ?? "";
    if (ct.startsWith("application/json")) {
      return JSON.parse(new TextDecoder().decode(bytes)) as T;
    }
    // Non-JSON bodies fall through to the caller as bytes, same as Python.
    return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as T;
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
   * Stream raw bytes from an endpoint. No retries: once the body starts
   * arriving, downstream consumers may have already moved state forward.
   *
   * Bounded by `opts` (see StreamOptions): total bytes, total duration,
   * and the wait for headers or for each chunk. Hitting a cap throws; the
   * body is cancelled and the request aborted whenever the generator
   * ends, including when the consumer breaks out early.
   */
  async *stream(
    method: string,
    path: string,
    params?: RequestOptions["params"],
    opts: StreamOptions = {},
  ): AsyncGenerator<Uint8Array, void, void> {
    const maxBytes = opts.maxBytes === undefined ? DEFAULT_STREAM_MAX_BYTES : opts.maxBytes;
    const maxDurationMs =
      opts.maxDurationMs === undefined ? DEFAULT_STREAM_MAX_DURATION_MS : opts.maxDurationMs;
    const idleMs = opts.idleTimeoutMs === undefined ? this.clientTimeoutMs : opts.idleTimeoutMs;
    const url = `${this.baseUrl}${path}${buildSearch(params)}`;
    const controller = new AbortController();
    const idleTimeout = () =>
      new EdgeLensTimeoutError(`stream ${path} was idle for longer than ${idleMs}ms`);

    let response: Response;
    try {
      response = await within(
        this.fetchImpl(url, {
          method,
          headers: this.headers(),
          signal: controller.signal,
          // Same as the request path.
          redirect: "manual",
        }),
        idleMs,
        idleTimeout,
      );
    } catch (e) {
      controller.abort();
      if (e instanceof EdgeLensError) throw e;
      throw new EdgeLensError(`HTTP transport error for ${method} ${path}: ${(e as Error).message}`);
    }
    if (response.status >= 300 && response.status < 400) {
      discard(response);
      controller.abort();
      throw new EdgeLensError(
        `Refusing to follow redirect from ${url} (status ${response.status}); ` +
          "the Bearer token would replay.",
      );
    }
    if (response.status >= 400 || !response.body) {
      discard(response);
      controller.abort();
      raiseForStatusHeadersOnly(response, path);
      throw new EdgeLensError("Stream response had no body");
    }

    const reader = response.body.getReader();
    const start = Date.now();
    let total = 0;
    let finished = false;
    try {
      while (true) {
        let wait = idleMs;
        let onTimeout = idleTimeout;
        if (maxDurationMs !== null) {
          const left = start + maxDurationMs - Date.now();
          if (wait === null || left < wait) {
            wait = left;
            onTimeout = () =>
              new EdgeLensError(
                `stream exceeded maxDurationMs (${maxDurationMs}); aborted after ` +
                  `${Date.now() - start}ms`,
              );
          }
        }
        const { value, done } = await within(reader.read(), wait, onTimeout);
        if (done) {
          finished = true;
          return;
        }
        if (!value) continue;
        total += value.byteLength;
        if (maxBytes !== null && total > maxBytes) {
          throw new EdgeLensError(
            `stream exceeded maxBytes (${maxBytes}); aborted after ${total} bytes`,
          );
        }
        yield value;
      }
    } finally {
      if (!finished) {
        controller.abort();
        reader.cancel().catch(() => undefined);
      }
    }
  }
}

function raiseForStatusHeadersOnly(response: Response, path: string): void {
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

/**
 * Settle with `p`, or reject with `onTimeout()` after `ms`. `null` waits
 * indefinitely. Works whether or not the fetch implementation honours the
 * abort signal.
 */
function within<T>(p: Promise<T>, ms: number | null, onTimeout: () => Error): Promise<T> {
  if (ms === null) return p;
  if (ms <= 0) {
    p.catch(() => undefined);
    return Promise.reject(onTimeout());
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(onTimeout()), ms);
  });
  return Promise.race([p, timeout]).finally(() => clearTimeout(timer));
}

/** Drop a body we will not read, so the connection is released. */
function discard(response: Response): void {
  response.body?.cancel().catch(() => undefined);
}

interface ReadBodyOptions {
  deadline: number;
  limit: number;
  onTimeout: () => Error;
  /** Throw this when the body passes `limit`; omitted, keep what fits. */
  onOverflow?: (total: number) => Error;
  abort?: () => void;
}

async function readBody(response: Response, o: ReadBodyOptions): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array(0);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let complete = false;
  try {
    while (true) {
      const { value, done } = await within(reader.read(), o.deadline - Date.now(), o.onTimeout);
      if (done) {
        complete = true;
        break;
      }
      if (!value) continue;
      if (total + value.byteLength > o.limit) {
        if (o.onOverflow) throw o.onOverflow(total + value.byteLength);
        chunks.push(value.subarray(0, o.limit - total));
        total = o.limit;
        break;
      }
      chunks.push(value);
      total += value.byteLength;
    }
  } finally {
    if (!complete) {
      o.abort?.();
      reader.cancel().catch(() => undefined);
    }
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.byteLength;
  }
  return out;
}

/** Control characters out, cut to MAX_ERROR_MESSAGE_CHARS. */
export function boundErrorMessage(text: string): string {
  const flat = text.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").trim();
  if (flat.length <= MAX_ERROR_MESSAGE_CHARS) return flat;
  return `${flat.slice(0, MAX_ERROR_MESSAGE_CHARS)}... (${flat.length - MAX_ERROR_MESSAGE_CHARS} more characters)`;
}

async function readErrorMessage(response: Response, deadline: number): Promise<string> {
  let text: string;
  try {
    const bytes = await readBody(response, {
      deadline,
      limit: MAX_ERROR_BODY_BYTES,
      onTimeout: () => new EdgeLensTimeoutError("error body read timed out"),
    });
    text = new TextDecoder().decode(bytes);
  } catch {
    return boundErrorMessage(response.statusText);
  }
  try {
    const data = JSON.parse(text) as Record<string, unknown>;
    const msg = data.message ?? data.error ?? data.detail;
    if (typeof msg === "string" && msg) return boundErrorMessage(msg);
  } catch {
    /* fall through */
  }
  return boundErrorMessage(text || response.statusText);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
