import { defineConfig, devices } from "@playwright/test";

// Browser tests (e2e/) run against the real stack started by e2e/run-e2e.sh.
// One worker, in file order: some tests change data (receive an order, add a user).
export default defineConfig({
  testDir: "e2e",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8082",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
