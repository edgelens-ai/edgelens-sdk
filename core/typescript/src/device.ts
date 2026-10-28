/**
 * Device interface — the primary surface customers use in tests.
 *
 * Mirrors `edgelens.device.Device` from the Python SDK, including the
 * `display` and `inference` namespaces.
 */

import { DeviceError, EdgeLensTimeoutError } from "./errors.js";
import { HTTPClient, opTimeoutMs } from "./http.js";
import type {
  DeviceConnection,
  DeviceInfo,
  ExecResult,
  InferenceSnapshot,
  InferenceStats,
  OSType,
  SSHCredentials,
} from "./types.js";

/** A file to upload: raw data, or data with the filename to give it on the device. */
type DeployFile = Blob | { name: string; blob: Blob };

class DisplayController {
  constructor(
    private readonly http: HTTPClient,
    private readonly sessionId: string,
  ) {}

  /** Play a video on the display. Source can be a URL the platform can fetch. */
  async play(source: string, loop = false): Promise<void> {
    await this.http.post(`/v1/sessions/${this.sessionId}/display/play`, {
      json: { source, loop },
    });
  }

  /** Show a still image on the display. */
  async show(source: string): Promise<void> {
    await this.http.post(`/v1/sessions/${this.sessionId}/display/show`, {
      json: { source },
    });
  }

  async stop(): Promise<void> {
    await this.http.post(`/v1/sessions/${this.sessionId}/display/stop`);
  }

  async status(): Promise<{ ready: boolean; state: string; source: string | null }> {
    return this.http.get(`/v1/sessions/${this.sessionId}/display/status`);
  }

  /** Wait for the display to settle into the requested state. */
  async waitStable(timeoutMs = 5_000, pollIntervalMs = 500): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const s = await this.status();
      if (s.ready) return;
      await sleep(pollIntervalMs);
    }
    throw new EdgeLensTimeoutError(`Display did not become stable within ${timeoutMs}ms`);
  }
}

class InferenceController {
  constructor(
    private readonly http: HTTPClient,
    private readonly sessionId: string,
    private readonly os: OSType,
  ) {}

  private checkSupported(): void {
    if (this.os === "recamagined") {
      throw new DeviceError(
        "Built-in inference is not available on reCamaginedOS. " +
          "Use device.exec() to run a customer-provided binary.",
      );
    }
  }

  async start(): Promise<void> {
    this.checkSupported();
    await this.http.post(`/v1/sessions/${this.sessionId}/inference/start`);
  }

  async stop(): Promise<void> {
    this.checkSupported();
    await this.http.post(`/v1/sessions/${this.sessionId}/inference/stop`);
  }

  /** Run one inference frame and return the result. */
  async once(): Promise<{ detections: unknown[]; frame_id: number; timestamp_ms: number }> {
    this.checkSupported();
    return this.http.get(`/v1/sessions/${this.sessionId}/inference/once`);
  }

  /** Current point-in-time metrics from a running inference. */
  async snapshot(): Promise<InferenceSnapshot> {
    this.checkSupported();
    return this.http.get(`/v1/sessions/${this.sessionId}/inference/stats`);
  }

  /**
   * Run inference for a duration and return aggregated stats. The HTTP
   * wait is extended to cover the requested duration.
   */
  async run(durationS = 30, collectFrames = false): Promise<InferenceStats> {
    this.checkSupported();
    return this.http.post(`/v1/sessions/${this.sessionId}/inference/results`, {
      json: { duration_s: durationS, collect_frames: collectFrames },
      timeoutMs: opTimeoutMs(this.http.timeoutMs, durationS),
    });
  }

  /** Wait for the model to load and produce at least one frame. */
  async waitReady(timeoutMs = 30_000, pollIntervalMs = 1_000): Promise<void> {
    this.checkSupported();
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const snap = await this.snapshot();
        if (snap.fps > 0) return;
      } catch (e) {
        if (!(e instanceof DeviceError)) throw e;
      }
      await sleep(pollIntervalMs);
    }
    throw new EdgeLensTimeoutError(`Inference did not become ready within ${timeoutMs}ms`);
  }

  /** Yield inference snapshots periodically for the given duration. */
  async *stream(
    durationMs = 30_000,
    intervalMs = 1_000,
  ): AsyncGenerator<InferenceSnapshot, void, void> {
    this.checkSupported();
    const deadline = Date.now() + durationMs;
    while (Date.now() < deadline) {
      yield await this.snapshot();
      await sleep(intervalMs);
    }
  }
}

export class Device {
  readonly display: DisplayController;
  readonly inference: InferenceController;

  constructor(
    private readonly http: HTTPClient,
    private readonly sessionId: string,
    private readonly connection: DeviceConnection,
  ) {
    this.display = new DisplayController(http, sessionId);
    this.inference = new InferenceController(http, sessionId, connection.os);
  }

  get mac(): string {
    return this.connection.mac;
  }

  get host(): string {
    return this.connection.host;
  }

  get os(): OSType {
    return this.connection.os;
  }

  get webUi(): string | undefined {
    return this.connection.web_ui;
  }

  /**
   * Upload a model, plus optional config and extra files, from local file
   * data. Pass each as a Blob, or `{ name, blob }` to set its filename
   * (a bare Blob is named after its part: `model`, `config`, `file_N`).
   *
   * On reCamaginedOS the files land in /userdata/Models/ readable but not
   * executable; `chmod +x` a deployed binary before running it.
   */
  async deploy(opts: {
    model: DeployFile;
    config?: DeployFile;
    files?: DeployFile[];
  }): Promise<{ success: boolean; detail?: string }> {
    if (!opts?.model) {
      throw new DeviceError("deploy() requires model");
    }
    const form = new FormData();
    const append = (part: string, file: DeployFile) => {
      const f = file instanceof Blob ? { name: part, blob: file } : file;
      form.append(part, f.blob, f.name);
    };
    append("model", opts.model);
    if (opts.config) append("config", opts.config);
    (opts.files ?? []).forEach((file, i) => append(`file_${i}`, file));
    return this.http.post(`/v1/sessions/${this.sessionId}/deploy`, { body: form });
  }

  /**
   * Run a command on the device via SSH (proxied through the platform).
   * The HTTP wait is extended to cover the requested command timeout.
   */
  async exec(command: string, timeoutS = 60): Promise<ExecResult> {
    return this.http.post<ExecResult>(`/v1/sessions/${this.sessionId}/exec`, {
      json: { command, timeout: timeoutS },
      timeoutMs: opTimeoutMs(this.http.timeoutMs, timeoutS),
    });
  }

  /** Get SSH credentials for direct connection (no platform proxy). */
  ssh(): SSHCredentials {
    return {
      user: this.connection.ssh_user,
      host: this.connection.host,
      port: this.connection.ssh_port,
      password: this.connection.ssh_password,
    };
  }

  /** Get the device info report (collect_device_info.sh output). */
  async info(): Promise<DeviceInfo> {
    return this.http.get<DeviceInfo>(`/v1/sessions/${this.sessionId}/info`);
  }

  /** Get the camera stream URL (stock OS only). */
  async streamUrl(): Promise<string> {
    if (this.os === "recamagined") {
      throw new DeviceError(
        "reCamaginedOS does not provide a built-in camera stream.",
      );
    }
    const data = await this.http.get<{ url: string }>(
      `/v1/sessions/${this.sessionId}/stream`,
    );
    return data.url;
  }

  /** Yield raw frame chunks from the device's stream (stock OS only). */
  async *stream(): AsyncGenerator<Uint8Array, void, void> {
    if (this.os === "recamagined") {
      throw new DeviceError(
        "reCamaginedOS does not provide a built-in camera stream.",
      );
    }
    yield* this.http.stream("GET", `/v1/sessions/${this.sessionId}/stream/raw`);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
