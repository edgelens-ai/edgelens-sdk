/**
 * Project presets for common (deviceType, os) combinations.
 *
 * Use in `playwright.config.ts`:
 *
 *   import { defineConfig } from "@playwright/test";
 *   import { edgelensProjects } from "@edgelens/playwright-plugin";
 *
 *   export default defineConfig({
 *     projects: [
 *       ...edgelensProjects({ apiKey: process.env.EDGELENS_API_KEY }),
 *     ],
 *   });
 *
 * Each project sets `edgelensOptions.session` to the matching combo.
 * Test files filter via `test.use({ ... })` or Playwright's project
 * tag mechanism (`test.describe.configure({ tag: ["@stock-os"] })`).
 */

import type { CreateSessionOptions, DeviceType, OSType } from "@edgelens/core";

import type { EdgelensFixtureOptions } from "./lifecycle.js";

export interface EdgelensProject {
  name: string;
  use: {
    edgelensOptions: EdgelensFixtureOptions;
  };
}

export interface EdgelensMatrixEntry {
  deviceType: DeviceType;
  os: OSType;
  sessionTimeoutS?: number;
}

export interface EdgelensProjectsOptions {
  apiKey?: string;
  baseUrl?: string;
  /** Which (deviceType, os) combos to expose. Defaults to all supported. */
  matrix?: EdgelensMatrixEntry[];
}

const DEFAULT_MATRIX: EdgelensMatrixEntry[] = [
  { deviceType: "recamera-2002", os: "stock-os" },
  { deviceType: "recamera-2002", os: "recamagined" },
];

export function edgelensProjects(
  opts: EdgelensProjectsOptions = {},
): EdgelensProject[] {
  const matrix = opts.matrix ?? DEFAULT_MATRIX;
  return matrix.map(({ deviceType, os, sessionTimeoutS }) => {
    const session: CreateSessionOptions = {
      deviceType,
      os,
      ...(sessionTimeoutS !== undefined ? { timeoutS: sessionTimeoutS } : {}),
    };
    return {
      name: `${deviceType}/${os}`,
      use: {
        edgelensOptions: {
          ...(opts.apiKey !== undefined ? { apiKey: opts.apiKey } : {}),
          ...(opts.baseUrl !== undefined ? { baseUrl: opts.baseUrl } : {}),
          session,
        },
      },
    };
  });
}
