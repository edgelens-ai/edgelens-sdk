# @edgelens/core

TypeScript client for the EdgeLens Edge AI Device Farm — the same surface as
the Python SDK (`pip install edgelens-sdk`), with the idioms a JS/TS user
expects.

## Install

```sh
npm install @edgelens/core
```

Requires Node 18+ (uses built-in `fetch`).

## Quickstart

```ts
import { readFile } from "node:fs/promises";
import { EdgeLensClient } from "@edgelens/core";

const client = new EdgeLensClient({ apiKey: process.env.EDGELENS_API_KEY! });

const session = await client.createSession({
  deviceType: "recamera-2002",
  os: "stock-os",
  timeoutS: 600,
});

await session.waitReady();

await session.device.deploy({
  model: { name: "face.cvimodel", blob: new Blob([await readFile("./face.cvimodel")]) },
});

await session.device.inference.start();
const stats = await session.device.inference.run(30);
console.log("avg fps:", stats.fps.avg);

await session.release();
```

## API surface

| Python (`edgelens`)              | TypeScript (`@edgelens/core`)               |
|----------------------------------|---------------------------------------------|
| `EdgeLensClient(api_key=...)`    | `new EdgeLensClient({ apiKey: ... })`       |
| `client.create_session(...)`     | `client.createSession({ ... })`             |
| `session.wait_ready(timeout=…)`  | `session.waitReady(timeoutMs, pollIntervalMs)` |
| `session.release()`              | `session.release()`                         |
| `session.device.exec("...")`     | `session.device.exec("...")`                |
| `session.device.deploy(model=…, files=[…])` | `session.device.deploy({ model, config?, files? })` (Blobs) |
| `session.device.display.play(...)` | `session.device.display.play(source, loop)` |
| `session.device.inference.run(30)` | `session.device.inference.run(30)`        |
| `RetryPolicy(...)`               | `new RetryPolicy({ ... })`                  |

Errors:

```ts
import {
  EdgeLensError,
  AuthenticationError,
  SessionError,
  DeviceError,
  EdgeLensTimeoutError,
} from "@edgelens/core";
```

## Retries

Idempotent methods (`GET`, `DELETE`, `HEAD`, `OPTIONS`) retry on transport
errors and on `429 / 502 / 503 / 504`. `Retry-After` is honored. `POST`
never retries by default — a retried create-session must not duplicate
sessions.

Override via:

```ts
import { EdgeLensClient, RetryPolicy } from "@edgelens/core";

const client = new EdgeLensClient({
  apiKey: "...",
  retryPolicy: new RetryPolicy({
    maxAttempts: 5,
    baseDelayMs: 200,
    maxDelayMs: 10_000,
  }),
});
```

## Streaming

`session.device.stream()` returns an async iterator of `Uint8Array`:

```ts
for await (const chunk of session.device.stream()) {
  await out.write(chunk);
}
```

A stream is capped, as in the Python SDK: 1 GiB in total, 600 s from the
response headers, and the client's `timeoutMs` while waiting for the
headers or for any one chunk. Hitting a cap throws. Pass `StreamOptions`
to change a cap, or `null` to disable it:

```ts
session.device.stream({ maxBytes: null, maxDurationMs: 3_600_000, idleTimeoutMs: 60_000 });
```

Leaving the loop early (`break`, `return`, an exception) cancels the body
and aborts the request.

Every other request is bounded by `timeoutMs` from start to the last byte
of the body, and its body by `maxResponseBytes` (64 MiB by default). Error
messages carry at most 512 characters of the server's text.

Inference snapshots stream too:

```ts
for await (const snap of session.device.inference.stream(60_000, 1_000)) {
  console.log(snap.fps, snap.detection_count);
}
```

## Base URL checks

The client refuses a `baseUrl` that would send the API key somewhere it
should not go, with the same rules as the Python SDK:

- `http://` unless `allowInsecureBaseUrl: true`;
- loopback, private and shared addresses (`127.0.0.0/8`, `10.0.0.0/8`,
  `100.64.0.0/10`, `fc00::/7`, ...) and `localhost`, unless
  `allowPrivateBaseUrl: true` or `EDGELENS_ALLOW_PRIVATE_BASE_URL=1`, for a
  server you control, for example a local test server;
- link-local, multicast, reserved and cloud metadata addresses
  (`169.254.169.254`, `fe80::/10`, `fd00:ec2::254`), always.

The two overrides are independent: a local `http://localhost` dev loop
needs both.

## Custom fetch (proxies, tests)

```ts
const client = new EdgeLensClient({
  apiKey: "...",
  fetch: myCustomFetch,
});
```

## Develop

```sh
npm install
npm run typecheck
npm test
npm run build
```
