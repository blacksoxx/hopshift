import { defineConfig } from "@playwright/test";

// End-to-end against the real API serving the built UI (run `npm run build` first).
//
// Default: an isolated server is started from the repository root by ui/e2e/serve.py on port
// 8765 with a fresh state directory, authentication required and model calls disabled. The
// suite creates the first administrator through the setup screen.
//
// Set PLAYWRIGHT_BASE_URL (e.g. http://127.0.0.1:8088 for the Docker stack) to test an
// already-running server instead; set VMA_PYTHON to pick the interpreter (default: python).
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;
const python = process.env.VMA_PYTHON ?? (process.env.CI ? "python" : "../.venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: externalBaseUrl ?? "http://127.0.0.1:8765", trace: "retain-on-failure" },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: `${python} e2e/serve.py --port 8765`,
        url: "http://127.0.0.1:8765/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 90_000,
        stdout: "pipe",
        stderr: "pipe",
      },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
