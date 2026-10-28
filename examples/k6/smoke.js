// 30-second smoke test — same shape as bench.js, short duration.
// Run: ./k6 run smoke.js
import edgelens from "k6/x/edgelens";
import { check } from "k6";

export const options = {
  vus: 1,
  duration: "30s",
  thresholds: {
    inference_fps: ["avg>10"],
    inference_latency_ms: ["p(95)<150"],
  },
};

// open() only works at init scope; the bytes are uploaded in setup().
const model = open("./models/face.cvimodel", "b");

export function setup() {
  const client = edgelens.connect({ apiKey: __ENV.EDGELENS_API_KEY });
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
  const stats = edgelens.resume(data.sessionId).device.inference.stats();
  check(stats, {
    "fps healthy": (s) => s.fps.avg > 0,
    "latency reported": (s) => s.latency_ms.p95 > 0,
  });
}

export function teardown(data) {
  edgelens.resume(data.sessionId).release();
}
