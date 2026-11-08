import { defineConfig } from "@playwright/test";

// End-to-end against the real API serving the built UI.
// Default: build first (`npm run build`); the web server is started from the repository root
// with the project's virtualenv on port 8765.
// Set PLAYWRIGHT_BASE_URL (e.g. http://127.0.0.1:8088 for the Docker stack) to test an
// already-running server instead.
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: { baseURL: externalBaseUrl ?? "http://127.0.0.1:8765", trace: "retain-on-failure" },
  webServer: externalBaseUrl
    ? undefined
    : {
        command: "cd .. && .venv/bin/python -m cli.main serve --port 8765",
        url: "http://127.0.0.1:8765/api/health",
        reuseExistingServer: true,
        timeout: 60_000,
      },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
