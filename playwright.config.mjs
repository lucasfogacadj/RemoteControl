import path from "node:path";
import { defineConfig } from "@playwright/test";

const baseURL = "http://127.0.0.1:8768";
const runId = process.env.PLAYWRIGHT_RUN_ID || `${Date.now()}-${process.pid}`;
const python = process.env.PYTHON_EXECUTABLE || ".\\.venv\\Scripts\\python.exe";

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  outputDir: "output/playwright/test-results",
  reporter: [
    ["line"],
    ["html", { outputFolder: "output/playwright/html-report", open: "never" }],
  ],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `"${python}" -m uvicorn hub.control_hub.main:app --host 127.0.0.1 --port 8768 --workers 1 --no-access-log --log-level warning`,
    url: `${baseURL}/health/ready`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: {
      ...process.env,
      CONTROL_DB_PATH: path.resolve(`output/playwright/e2e-${runId}.db`),
      CONTROL_PAIRING_TOKEN: "playwright-token",
      CONTROL_SCHEDULER_TICK_SECONDS: "60",
      CONTROL_SHUTDOWN_TIMEOUT_SECONDS: "1",
    },
  },
});
