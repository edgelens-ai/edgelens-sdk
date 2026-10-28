import { defineConfig } from "@playwright/test";
import { edgelensProjects } from "@edgelens/playwright-plugin";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false, // EdgeLens sessions take ~30s to provision; serialize.
  retries: 0,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    actionTimeout: 30_000,
    trace: "retain-on-failure",
  },
  projects: [
    ...edgelensProjects({
      deviceType: "recamera-2002",
      oses: ["stock-os", "recamagined"],
    }),
  ],
});
