import { defineConfig, devices } from "@playwright/test";

// This profile cannot reach a real backend: Next proxies only to the fixture.
// Default is the production standalone server (what the image runs); set
// CHAT_REVIEW_SERVER=dev to iterate against `next dev` instead.
const FIXTURE_URL = "http://127.0.0.1:8101";
const useDev = process.env.CHAT_REVIEW_SERVER === "dev";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "chat-review.spec.ts",
  workers: 1,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3101" },
  webServer: [
    { command: "node e2e/support/chat-review-server.mjs", url: `${FIXTURE_URL}/health`, reuseExistingServer: false },
    {
      command: useDev
        ? "npm run dev -- --hostname 127.0.0.1 --port 3101"
        : "node e2e/support/start-chat-review-frontend.mjs",
      url: "http://127.0.0.1:3101/login",
      reuseExistingServer: false,
      env: { BACKEND_INTERNAL_URL: FIXTURE_URL, NEXT_PUBLIC_API_URL: "/api/v1" },
      timeout: 60000,
    },
  ],
});
