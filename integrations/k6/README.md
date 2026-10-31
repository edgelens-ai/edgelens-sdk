# xk6-edgelens

[k6](https://k6.io) extension for the EdgeLens Edge AI Device Farm.
Sustained-load benchmarks against a real reCamera with k6's threshold
engine gating CI.

The extension is distributed as source: build it into a custom `k6`
binary with `xk6`, as below. Its calls go to the EdgeLens API.

## Install

k6 extensions are compiled into a custom `k6` binary via
[`xk6`](https://github.com/grafana/xk6):

```sh
go install go.k6.io/xk6/cmd/xk6@latest
xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6
```

This drops a `./k6` binary in the current directory. Put it on your
`$PATH` or invoke with `./k6 run …`.

## Quickstart

```js
import edgelens from "k6/x/edgelens";
import { check } from "k6";

export const options = {
  scenarios: {
    soak: { executor: "constant-vus", vus: 1, duration: "10m" },
  },
  thresholds: {
    inference_fps: ["avg>15"],
    inference_latency_ms: ["p(95)<100"],
  },
};

// Files must be opened at init scope (a k6 rule); upload them in setup().
const model = open("./models/face.cvimodel", "b");

// One client per VU at init scope: setup(), the default function and
// teardown() all use the same key and base URL. connect() throws if the
// key is empty.
const client = edgelens.connect({ apiKey: __ENV.EDGELENS_API_KEY });

export function setup() {
  const session = client.createSession({
    deviceType: "recamera-2002",
    os: "stock-os",
  });
  session.waitReady({ timeout: 600 });
  session.device.deploy({ model: { name: "face.cvimodel", data: model } });
  session.device.inference.start();
  return { sessionId: session.id };
}

export default function (data) {
  const stats = client.resume(data.sessionId).device.inference.stats();
  check(stats, {
    "fps holding": (s) => s.fps.avg >= 15,
    "p95 latency": (s) => s.latency_ms.p95 < 100,
  });
}

export function teardown(data) {
  client.resume(data.sessionId).release();
}
```

Run:

```sh
./k6 run bench.js
```

## Module surface

| JS symbol | What |
|---|---|
| `edgelens.connect({apiKey, baseUrl?, allowInsecureBaseUrl?, allowPrivateBaseUrl?})` | Returns a `Client`. Call it at init scope. Throws if `apiKey` is empty, or if `baseUrl` is `http://` without `allowInsecureBaseUrl: true`, or names a loopback, private or shared address (or `localhost`) without `allowPrivateBaseUrl: true` or `EDGELENS_ALLOW_PRIVATE_BASE_URL=1`. A link-local, reserved or cloud metadata host is always refused. The same rules as the Python and TypeScript clients. |
| `client.createSession({deviceType, os, imageVersion?, timeout?})` | Allocates a device. |
| `client.resume(sessionId)` | Re-attaches to an existing session by id, with this client's key and base URL. Use it in the default function and in `teardown()`. |
| `session.waitReady({timeout?, pollInterval?})` | Block until `status=ready`. |
| `session.device.deploy({model, config?, files?})` | Upload a model, plus optional config and extra files. Each is `{ name, data }`, where `data` comes from `open(path, "b")` at init scope. The upload times out after 10 minutes. |
| `session.device.inference.start() / .stop()` | Toggle the built-in engine (`stock-os` only). |
| `session.device.inference.stats()` | Snapshot + emit metrics. |
| `session.device.inference.run(duration)` | Block `duration` seconds, return + emit aggregated stats. |
| `session.device.exec(cmd, {timeout?})` | Shell command via SSH. |
| `session.release()` | Release the device. |

## Metrics

The extension registers two k6 trend metrics:

- `inference_fps` — pushed on every `stats()` / `run()` call with `s.fps.avg`.
- `inference_latency_ms` — pushed with `s.latency_ms.p95`, tagged as a Time metric.

Both are tagged with `session_id` so multi-session VUs are
distinguishable in the result CSV / cloud upload.

Wire them into thresholds:

```js
thresholds: {
  inference_fps: ["avg>15"],
  inference_latency_ms: ["p(95)<100", "p(99)<200"],
}
```

k6 exits non-zero on any threshold breach.

## Build (for development)

```sh
cd integrations/k6
go mod tidy
go build ./...        # validates the package compiles
```

The unit tests run in a pinned golang container from the repo root, with
no Go on the host:

```sh
make test-go
```

To test against a local k6 development build:

```sh
xk6 build --with github.com/edgelens-ai/edgelens-sdk/integrations/k6=$(pwd)
```

The trailing `=$(pwd)` tells xk6 to use this directory as the module
source instead of fetching from GitHub.

## Anti-patterns

- One session per VU iteration — sessions take ~30 s to provision.
  Allocate in `setup()`, attach via `client.resume(sessionId)` in
  the default function.
- Threshold expressions referencing metrics the extension doesn't emit
  (for example `inference_detection_count`). The emitted metrics are
  listed above.
- Polling `inference.stats()` from a JavaScript `for` loop — let k6's
  executor manage iteration cadence (`vus + duration` or `iterations`).

## Example project

[`examples/k6/`](../../examples/k6/) — copy-pasteable soak + smoke
scripts.
