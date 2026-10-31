/**
 * Top-level EdgeLens client.
 *
 * ```ts
 * import { readFile } from "node:fs/promises";
 * import { EdgeLensClient } from "@edgelens/core";
 *
 * const client = new EdgeLensClient({ apiKey: process.env.EDGELENS_API_KEY! });
 * const session = await client.createSession({ deviceType: "recamera-2002", os: "stock-os" });
 * await session.waitReady();
 * const model = new Blob([await readFile("./face.cvimodel")]);
 * await session.device.deploy({ model: { name: "face.cvimodel", blob: model } });
 * const stats = await session.device.inference.run(30);
 * console.log("avg fps:", stats.fps.avg);
 * await session.release();
 * ```
 */

import { AuthenticationError } from "./errors.js";
import {
  DEFAULT_BASE_URL,
  HTTPClient,
  RetryPolicy,
  sessionPath,
  type RetryPolicyOptions,
} from "./http.js";
import { Session } from "./session.js";
import type { DeviceType, OSType, SessionResponse } from "./types.js";

export interface EdgeLensClientOptions {
  /** API key. If omitted, reads `EDGELENS_API_KEY` from env. */
  apiKey?: string;
  baseUrl?: string;
  /** Per-request HTTP timeout in milliseconds. Default 30s. */
  timeoutMs?: number;
  retryPolicy?: RetryPolicy | RetryPolicyOptions;
  userAgent?: string;
  /** Inject a custom fetch (tests / proxies). Defaults to global fetch. */
  fetch?: typeof fetch;
  /** Allow an http:// baseUrl. Default false. Forwarded to HTTPClient. */
  allowInsecureBaseUrl?: boolean;
  /**
   * Allow a loopback/private baseUrl host for a server you control, for
   * example a local test server. Defaults to `EDGELENS_ALLOW_PRIVATE_BASE_URL`. Forwarded to
   * HTTPClient.
   */
  allowPrivateBaseUrl?: boolean;
  /** Largest response body to buffer. Forwarded to HTTPClient. */
  maxResponseBytes?: number;
}

export interface CreateSessionOptions {
  deviceType?: DeviceType;
  os?: OSType;
  /** Max session duration in seconds. */
  timeoutS?: number;
  /** Pin a specific OS image version for the session. */
  imageVersion?: string;
}

export class EdgeLensClient {
  private readonly http: HTTPClient;

  constructor(opts: EdgeLensClientOptions = {}) {
    const apiKey = opts.apiKey ?? process.env.EDGELENS_API_KEY;
    if (!apiKey) {
      throw new AuthenticationError(
        "No API key provided. Pass { apiKey } or set EDGELENS_API_KEY.",
      );
    }
    const retry =
      opts.retryPolicy instanceof RetryPolicy
        ? opts.retryPolicy
        : opts.retryPolicy
          ? new RetryPolicy(opts.retryPolicy)
          : undefined;
    this.http = new HTTPClient({
      apiKey,
      baseUrl: opts.baseUrl ?? DEFAULT_BASE_URL,
      ...(opts.timeoutMs !== undefined ? { timeoutMs: opts.timeoutMs } : {}),
      ...(retry ? { retryPolicy: retry } : {}),
      ...(opts.userAgent !== undefined ? { userAgent: opts.userAgent } : {}),
      ...(opts.fetch ? { fetch: opts.fetch } : {}),
      ...(opts.allowInsecureBaseUrl ? { allowInsecureBaseUrl: true } : {}),
      ...(opts.allowPrivateBaseUrl !== undefined
        ? { allowPrivateBaseUrl: opts.allowPrivateBaseUrl }
        : {}),
      ...(opts.maxResponseBytes !== undefined
        ? { maxResponseBytes: opts.maxResponseBytes }
        : {}),
    });
  }

  /**
   * Allocate a new device session.
   *
   * The session is allocated asynchronously. The returned `Session`
   * has `status === "flashing"` (or an error state). Call
   * `await session.waitReady()` before using `session.device`.
   */
  async createSession(opts: CreateSessionOptions = {}): Promise<Session> {
    const data = await this.http.post<SessionResponse>("/v1/sessions", {
      json: {
        device_type: opts.deviceType ?? "recamera-2002",
        os: opts.os ?? "stock-os",
        timeout: opts.timeoutS ?? 3600,
        ...(opts.imageVersion ? { image_version: opts.imageVersion } : {}),
      },
    });
    return Session.fromApi(this.http, data);
  }

  /** Retrieve an existing session by id. */
  async getSession(sessionId: string): Promise<Session> {
    const data = await this.http.get<SessionResponse>(sessionPath(sessionId));
    return Session.fromApi(this.http, data);
  }
}
