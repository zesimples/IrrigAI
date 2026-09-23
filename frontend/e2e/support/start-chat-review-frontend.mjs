// Serve the production standalone build exactly as the frontend image does
// (`node server.js` with .next/static and public beside it), not `next dev`:
// response compression and buffering differ between the two, and buffering is
// the failure this suite exists to catch.
import { cpSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";

const root = new URL("../../", import.meta.url).pathname;
const standalone = `${root}.next/standalone`;
if (!existsSync(`${standalone}/server.js`)) {
  console.error("No standalone build: run `npm run e2e:chat-review` (it builds first).");
  process.exit(1);
}
cpSync(`${root}.next/static`, `${standalone}/.next/static`, { recursive: true });
cpSync(`${root}public`, `${standalone}/public`, { recursive: true });

const server = spawn("node", ["server.js"], {
  cwd: standalone,
  stdio: "inherit",
  env: { ...process.env, PORT: "3101", HOSTNAME: "127.0.0.1", NODE_ENV: "production" },
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
