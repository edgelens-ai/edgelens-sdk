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

Inference snapshots stream too:

```ts
for await (const snap of session.device.inference.stream(60_000, 1_000)) {
  console.log(snap.fps, snap.detection_count);
}
```

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
