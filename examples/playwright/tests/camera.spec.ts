import { readFile } from "node:fs/promises";
import { test, expect } from "@edgelens/playwright-plugin";

// deploy() uploads local file data; read each file into a Blob.
const upload = async (path: string) => ({
  name: path.split("/").pop()!,
  blob: new Blob([await readFile(path)]),
});

// stock-os: built-in display + inference engine -------------------------------

test.describe("stock-os", () => {
  test.skip(({ os }) => os !== "stock-os", "stock-os only");

  test("kiosk shows test pattern", async ({ device, page }) => {
    await device.display.show("https://example.com/test-pattern.png");
    await device.display.waitStable();

    await page.goto(`http://${device.host}:8000/preview`);
    await expect(page).toHaveScreenshot("test-pattern.png", {
      maxDiffPixelRatio: 0.02,
    });
  });

  test("inference holds the latency budget", async ({ device }) => {
    await device.deploy({ model: await upload("./models/face.cvimodel") });
    await device.inference.start();
    const stats = await device.inference.run(30);
    expect(stats.fps.avg).toBeGreaterThanOrEqual(15);
    expect(stats.latency_ms.p95).toBeLessThan(100);
  });

  test("camera serves preview on host", async ({ device, page }) => {
    const res = await page.goto(`http://${device.host}:8000/preview`);
    expect(res?.status()).toBe(200);
  });
});

// recamagined: ship your own binary ------------------------------------------

test.describe("recamagined", () => {
  test.skip(({ os }) => os !== "recamagined", "recamagined only");

  test("custom binary logs to stdout", async ({ device }) => {
    // Deployed files land in /userdata/Models/ without the executable bit.
    await device.deploy({
      model: await upload("./models/face.cvimodel"),
      files: [await upload("./build/my_inference")],
    });
    const r = await device.exec(
      "chmod +x /userdata/Models/my_inference && /userdata/Models/my_inference --probe",
    );
    expect(r.success).toBe(true);
    expect(r.stdout).toContain("READY");
  });
});
