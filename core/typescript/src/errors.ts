/**
 * Error hierarchy — mirrors `edgelens.errors`.
 */

export class EdgeLensError extends Error {
  override name = "EdgeLensError";
}

export class AuthenticationError extends EdgeLensError {
  override name = "AuthenticationError";
}

export class SessionError extends EdgeLensError {
  override name = "SessionError";
}

export class DeviceError extends EdgeLensError {
  override name = "DeviceError";
}

export class EdgeLensTimeoutError extends EdgeLensError {
  override name = "EdgeLensTimeoutError";
}
