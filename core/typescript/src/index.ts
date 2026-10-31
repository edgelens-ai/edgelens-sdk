export { EdgeLensClient } from "./client.js";
export type { EdgeLensClientOptions, CreateSessionOptions } from "./client.js";
export { Session } from "./session.js";
export { Device } from "./device.js";
export {
  HTTPClient,
  RetryPolicy,
  DEFAULT_BASE_URL,
  DEFAULT_MAX_RESPONSE_BYTES,
  DEFAULT_STREAM_MAX_BYTES,
  DEFAULT_STREAM_MAX_DURATION_MS,
  MAX_ERROR_MESSAGE_CHARS,
} from "./http.js";
export type { RetryPolicyOptions, HTTPClientOptions, StreamOptions } from "./http.js";
export { classifyHost } from "./baseurl.js";
export type { HostClass } from "./baseurl.js";
export {
  EdgeLensError,
  AuthenticationError,
  SessionError,
  DeviceError,
  EdgeLensTimeoutError,
} from "./errors.js";
export type {
  DeviceType,
  OSType,
  SessionStatus,
  BBox,
  Detection,
  PercentileStats,
  InferenceStats,
  InferenceSnapshot,
  DeviceConnection,
  DeviceInfo,
  SSHCredentials,
  SessionResponse,
  ExecResult,
} from "./types.js";
