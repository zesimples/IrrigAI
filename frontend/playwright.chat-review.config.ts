import { defineConfig, devices } from "@playwright/test";

// This profile cannot reach a real backend: Next proxies only to the fixture.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "chat-review.spec.ts",
  workers: 1,
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3101" },
  webServer: [
    { command: "node e2e/support/chat-review-server.mjs", url: "http://127.0.0.1:8101/health", reuseExistingServer: false },
    { command: "npm run dev -- --hostname 127.0.0.1 --port 3101", url: "http://127.0.0.1:3101/login", reuseExistingServer: false,
      env: { BACKEND_INTERNAL_URL: "http://127.0.0.1:8101", NEXT_PUBLIC_API_URL: "/api/v1" }, timeout: 60000 },
  ],
});
