import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // In CI: servers started by docker compose — just connect.
  // Locally: start dev servers automatically if not already running.
  webServer: process.env.CI
    ? []
    : [
        {
          command: `cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000`,
          url: `${BACKEND_URL}/health`,
          reuseExistingServer: true,
          timeout: 30_000,
        },
        {
          command: "npm run dev",
          url: BASE_URL,
          reuseExistingServer: true,
          timeout: 60_000,
        },
      ],
});
