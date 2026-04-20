import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E config — runs against the live Docker stack.
 * Start services first: docker compose up -d
 *
 * Usage:
 *   pnpm e2e               # headless Chromium
 *   pnpm e2e --headed      # visible browser
 *   pnpm e2e --grep P3-3   # single test by tag
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://localhost:3002",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "on-first-retry",
  },
  projects: [
    {
      name: "setup",
      testMatch: /global-setup\.ts/,
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/user.json",
      },
      dependencies: ["setup"],
    },
  ],
});
