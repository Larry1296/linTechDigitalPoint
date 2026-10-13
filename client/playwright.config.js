import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:5174",
    trace: "retain-on-failure",
  },
  // On GitHub, failures also show as notes on the run, readable without opening the logs.
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
});
