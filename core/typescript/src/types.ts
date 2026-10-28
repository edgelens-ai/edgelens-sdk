/**
 * Type definitions mirroring `edgelens.types` in the Python SDK.
 *
 * Enum-like string literal unions are preferred over `enum` so the
 * library composes cleanly with consumers that strip TypeScript at
 * build time and so the wire format is self-evident.
 */

export type DeviceType = "recamera-2002";
export type OSType = "stock-os" | "recamagined";
export type SessionStatus =
  | "pending"
  | "allocating"
  | "flashing"
  | "ready"
  | "expired"
  | "released"
  | "error";

export interface BBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Detection {
  label: string;
  confidence: number;
  bbox?: BBox;
  frame?: number;
}

export interface PercentileStats {
  avg: number;
  min: number;
  max: number;
  p50: number;
  p95: number;
  p99: number;
}

export interface InferenceStats {
  duration_s: number;
  total_frames: number;
  fps: PercentileStats;
  latency_ms: PercentileStats;
  detections: Detection[];
  memory?: Record<string, unknown>;
  temperature_c?: Record<string, unknown>;
}

export interface InferenceSnapshot {
  fps: number;
  latency_ms: number;
  detection_count: number;
  temperature_c?: number;
}

export interface DeviceConnection {
  mac: string;
  host: string;
  ssh_port: number;
  ssh_user: string;
  ssh_password: string;
  web_ui?: string;
  os: OSType;
}

export interface DeviceInfo {
  collected_at: string;
  hostname: string;
  hardware: Record<string, unknown>;
  firmware: Record<string, unknown>;
  storage: Record<string, unknown>;
  network: Record<string, unknown>;
  peripherals: Record<string, unknown>;
  npu: Record<string, unknown>;
  system: Record<string, unknown>;
  logs: Record<string, unknown>;
}

export interface SSHCredentials {
  user: string;
  host: string;
  port: number;
  password: string;
}

export interface SessionResponse {
  id: string;
  status: SessionStatus;
  device?: DeviceConnection | null;
  created_at?: string;
  expires_at?: string;
  ready_at?: string;
  released_at?: string;
  returned_at?: string;
}

export interface ExecResult {
  stdout: string;
  stderr: string;
  exit_code: number;
}
