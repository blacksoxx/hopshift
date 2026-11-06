import { defineConfig } from "@playwright/test";

// End-to-end against the real API serving the built UI. Build first (`npm run build`); the
// web server is started from the repository root with the project's virtualenv.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:8765", trace: "retain-on-failure" },
  webServer: {
    command: "cd .. && .venv/bin/python -m cli.main serve --port 8765",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: true,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
