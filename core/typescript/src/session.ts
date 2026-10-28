/**
 * Session lifecycle. Mirrors `edgelens.session.Session`.
 */

import { Device } from "./device.js";
import { EdgeLensTimeoutError, SessionError } from "./errors.js";
import { HTTPClient } from "./http.js";
import type { DeviceConnection, SessionResponse, SessionStatus } from "./types.js";

const TERMINAL_FAIL: Set<SessionStatus> = new Set(["error", "expired", "released"]);

export class Session {
  readonly id: string;
  status: SessionStatus;
  expiresAt: string | undefined;
  readonly readyAt: string | undefined;
  readonly releasedAt: string | undefined;
  readonly returnedAt: string | undefined;

  private connection: DeviceConnection | undefined;
  private cachedDevice: Device | undefined;

  private constructor(
    private readonly http: HTTPClient,
    init: SessionResponse,
  ) {
    this.id = init.id;
    this.status = init.status;
    this.expiresAt = init.expires_at;
    this.readyAt = init.ready_at;
    this.releasedAt = init.released_at;
    this.returnedAt = init.returned_at;
    if (init.device) {
      this.connection = init.device;
      this.cachedDevice = new Device(http, init.id, init.device);
    }
  }

  /** @internal */
  static fromApi(http: HTTPClient, data: SessionResponse): Session {
    return new Session(http, data);
  }

  /**
   * The Device for this session. Throws if the session is not yet
   * ready. Call `waitReady()` first.
   */
  get device(): Device {
    if (!this.cachedDevice) {
      throw new SessionError(
        `Session ${this.id} is not ready (status=${this.status}). Call waitReady() first.`,
      );
    }
    return this.cachedDevice;
  }

  /** Re-fetch state from the API. */
  async refresh(): Promise<this> {
    const data = await this.http.get<SessionResponse>(`/v1/sessions/${this.id}`);
    this.status = data.status;
    this.expiresAt = data.expires_at;
    if (data.device) {
      this.connection = data.device;
      this.cachedDevice = new Device(this.http, this.id, data.device);
    }
    return this;
  }

  /**
   * Block until the session is ready, errors, or expires.
   *
   * @param timeoutMs - max wait
   * @param pollIntervalMs - between status fetches
   */
  async waitReady(timeoutMs = 300_000, pollIntervalMs = 2_000): Promise<this> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await this.refresh();
      if (this.status === "ready") return this;
      if (TERMINAL_FAIL.has(this.status)) {
        throw new SessionError(
          `Session ${this.id} ended in state ${this.status} before becoming ready`,
        );
      }
      await sleep(pollIntervalMs);
    }
    throw new EdgeLensTimeoutError(
      `Session ${this.id} did not become ready within ${timeoutMs}ms`,
    );
  }

  /** End the session and release the device. Idempotent. */
  async release(): Promise<void> {
    if (this.status === "released") return;
    await this.http.delete(`/v1/sessions/${this.id}`);
    this.status = "released";
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
