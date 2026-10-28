/**
 * Fixture lifecycle helpers — the actual session-allocation +
 * release logic. Kept separate from `fixtures.ts` so it's easy to
 * unit-test without Playwright's runner.
 */

import { EdgeLensClient } from "@edgelens/core";
import type {
  CreateSessionOptions,
  EdgeLensClientOptions,
  Session,
} from "@edgelens/core";

export interface EdgelensFixtureOptions {
  /** API key. Falls back to `EDGELENS_API_KEY` env var. */
  apiKey?: string;
  /** Override the platform API base URL. */
  baseUrl?: string;
  /** Per-test session params. Same shape as `client.createSession()`. */
  session?: CreateSessionOptions;
  /** How long to wait for `status=ready`. Default 5 minutes. */
  waitReadyTimeoutMs?: number;
  /** Test poll interval while waiting for ready. Default 2s. */
  waitReadyPollMs?: number;
  /** Extra options passed through to the underlying HTTP client. */
  client?: Pick<EdgeLensClientOptions, "timeoutMs" | "retryPolicy" | "userAgent" | "fetch">;
}

export const DEFAULTS = {
  waitReadyTimeoutMs: 5 * 60_000,
  waitReadyPollMs: 2_000,
} as const;

export function buildClient(opts: EdgelensFixtureOptions): EdgeLensClient {
  return new EdgeLensClient({
    ...(opts.apiKey !== undefined ? { apiKey: opts.apiKey } : {}),
    ...(opts.baseUrl !== undefined ? { baseUrl: opts.baseUrl } : {}),
    ...(opts.client ?? {}),
  });
}

/**
 * Allocate a session and wait for it to be ready.
 *
 * Thrown errors propagate to the test (Playwright will fail the
 * fixture setup); the caller is responsible for invoking
 * `releaseSession()` on the result in a `finally` to avoid leaking
 * a billable device.
 */
export async function allocateSession(
  client: EdgeLensClient,
  opts: EdgelensFixtureOptions = {},
): Promise<Session> {
  const session = await client.createSession(opts.session ?? {});
  await session.waitReady(
    opts.waitReadyTimeoutMs ?? DEFAULTS.waitReadyTimeoutMs,
    opts.waitReadyPollMs ?? DEFAULTS.waitReadyPollMs,
  );
  return session;
}

/**
 * Release a session, swallowing any errors that fire during
 * teardown (a failing release shouldn't mask the actual test
 * failure that preceded it).
 */
export async function releaseSession(
  session: Session | undefined,
  onError?: (err: unknown) => void,
): Promise<void> {
  if (!session) return;
  try {
    await session.release();
  } catch (e) {
    if (onError) onError(e);
  }
}
