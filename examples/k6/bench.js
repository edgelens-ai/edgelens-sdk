// 10-minute sustained inference benchmark.
// Gates on inference_fps avg>15 and inference_latency_ms p(95)<100.
//
// Run: ./k6 run bench.js
import edgelens from "k6/x/edgelens";
import { check } from "k6";

export const options = {
  scenarios: {
    soak: {
      executor: "constant-vus",
      vus: 1,
      duration: "10m",
    },
  },
  thresholds: {
    inference_fps: ["avg>15"],
    inference_latency_ms: ["p(95)<100", "p(99)<200"],
  },
};

// open() only works at init scope; the bytes are uploaded in setup().
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
  const session = client.resume(data.sessionId);
  const stats = session.device.inference.stats();
  check(stats, {
    "fps holding above 15": (s) => s.fps.avg >= 15,
    "p95 latency under 100ms": (s) => s.latency_ms.p95 < 100,
    "no detection regression": (s) => s.detection_count > 0,
  });
}

export function teardown(data) {
  client.resume(data.sessionId).release();
}
