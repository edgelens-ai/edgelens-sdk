import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // The plugin is tested against the core sources in this checkout, not a
  // built core/typescript/dist, so a core change is exercised here without
  // a build step and the two packages cannot drift apart unnoticed.
  resolve: {
    alias: {
      "@edgelens/core": fileURLToPath(
        new URL("../../core/typescript/src/index.ts", import.meta.url),
      ),
    },
  },
  test: {
    globals: false,
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
