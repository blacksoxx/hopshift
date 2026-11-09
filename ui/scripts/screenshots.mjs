// Captures the README / docs screenshots against a running server.
//
//   cd ui && npm run build
//   (cd .. && .venv/bin/python ui/e2e/serve.py --port 8765 --state-dir /tmp/vma-shots &)
//   node scripts/screenshots.mjs http://127.0.0.1:8765
//
// The script creates the first administrator when the server is fresh (or signs in), creates
// and approves a run from the bundled fixture, adds an environment connection, and writes PNGs
// to docs/images/. Run it from the ui/ folder so @playwright/test resolves.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] ?? "http://127.0.0.1:8765";
const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(here, "../../docs/images");
const fixture = path.resolve(here, "../../tests/fixtures/discovery_multi_vm.json");
fs.mkdirSync(out, { recursive: true });

const ADMIN = { username: "admin", password: "correct-horse-battery-staple-42", name: "Youssef" };

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: "light" });
const page = await context.newPage();

async function shot(name, { dark = false } = {}) {
  if (dark) await page.emulateMedia({ colorScheme: "dark" });
  await page.evaluate((isDark) => {
    localStorage.setItem("vma.theme", isDark ? "dark" : "light");
    document.documentElement.classList.toggle("dark", isDark);
  }, dark);
  await page.waitForTimeout(350);
  await page.screenshot({ path: path.join(out, `${name}.png`) });
  console.log("saved", name);
}

async function signIn() {
  await page.goto(`${base}/#/`, { waitUntil: "networkidle" });
  const landing = page.locator('[data-testid="setup-form"], [data-testid="login-form"], [data-testid="stat-runs"]').first();
  await landing.waitFor({ timeout: 30_000 });
  const kind = await landing.getAttribute("data-testid");
  if (kind === "setup-form") {
    await page.getByTestId("setup-username").fill(ADMIN.username);
    await page.getByTestId("setup-name").fill(ADMIN.name);
    await page.getByTestId("setup-password").fill(ADMIN.password);
    await page.getByTestId("setup-confirm").fill(ADMIN.password);
    await page.getByTestId("setup-submit").click();
  } else if (kind === "login-form") {
    await page.getByTestId("login-username").fill(ADMIN.username);
    await page.getByTestId("login-password").fill(ADMIN.password);
    await page.getByTestId("login-submit").click();
  }
  await page.waitForSelector('[data-testid="stat-runs"]', { timeout: 30_000 });
}

async function createRun(name, { approve = true, tags = ["lab"], validate = false } = {}) {
  await page.goto(`${base}/#/runs/new`, { waitUntil: "networkidle" });
  await page.waitForSelector("[data-testid=dropzone]");
  await page.getByTestId("discovery-file").setInputFiles(fixture);
  await page.waitForSelector('[data-testid="discovery-summary"]');
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("run-name").fill(name);
  await page.getByTestId("owner").fill("platform-team");
  for (const tag of tags) {
    await page.getByTestId("run-tags").fill(tag);
    await page.keyboard.press("Enter");
  }
  if (!validate) await page.getByTestId("toggle-validation").click(); // offline: no provider downloads
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("start-run").click();
  await page.waitForURL(/#\/runs\/\d{8}T/);
  const runId = page.url().split("/runs/")[1].split("/")[0];
  await page.waitForSelector('[data-testid="paused-banner"]', { timeout: 120_000 });
  if (!approve) return runId;
  await page.getByTestId("approve").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="paused-banner"]')?.textContent?.includes("approve_output"), null, { timeout: 240_000 });
  await page.getByTestId("approve").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="status-badge"]')?.textContent?.trim() === "succeeded", null, { timeout: 240_000 });
  return runId;
}

await signIn();

// data: one succeeded run, one paused run, one connection
// validated for real (terraform, tflint, OPA) so the compliance report has content
const succeeded = await createRun("prod-cluster lift-and-shift", { tags: ["prod", "wave-1"], validate: true });
await createRun("lab vCenter rehearsal", { approve: false, tags: ["lab"] });
await page.goto(`${base}/#/connections`, { waitUntil: "networkidle" });
if ((await page.getByTestId("connection-row").count()) === 0) {
  await page.getByTestId("add-connection").click();
  await page.getByTestId("provider-aws").click();
  await page.getByTestId("method-environment").click();
  await page.getByTestId("connection-name").fill("aws-landing-zone");
  await page.getByTestId("field-region").fill("eu-west-1");
  await page.getByTestId("connection-submit").click();
  await page.waitForSelector('[data-testid="connection-test-result"]', { timeout: 30_000 });
}

await page.goto(`${base}/#/`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="stat-runs"]');
await page.waitForTimeout(800);
await shot("dashboard");
await shot("dashboard-dark", { dark: true });
await page.emulateMedia({ colorScheme: "light" });

await page.goto(`${base}/#/runs`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="run-row"]');
await shot("runs");

await page.goto(`${base}/#/runs/${succeeded}`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="step-reporter"]');
await page.waitForTimeout(600);
await shot("run-detail");
await page.getByTestId("tab-cim").click();
await page.waitForSelector('[data-testid="unit-name-0"], [data-testid="cim-table"]', { timeout: 10_000 }).catch(() => undefined);
await page.waitForTimeout(400);
await shot("cim");
await page.getByTestId("tab-compliance").click();
await page.waitForSelector('[data-testid="compliance-report"]', { timeout: 10_000 });
await page.waitForTimeout(400);
await shot("compliance");
await page.getByTestId("tab-deploy").click();
await page.waitForTimeout(800);
await shot("deploy");
await page.getByTestId("tab-artifacts").click();
await page.waitForSelector('[data-testid="artifact-item"]');
await page.getByTestId("artifact-item").filter({ hasText: "compute_web-01.tf" }).first().click();
await page.waitForTimeout(900);
await shot("artifacts");

await page.goto(`${base}/#/connections`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="connection-row"]');
await shot("connections");

await page.goto(`${base}/#/assess`, { waitUntil: "networkidle" });
await page.getByTestId("discovery-file").setInputFiles(fixture);
await page.getByTestId("run-assess").click();
await page.waitForSelector('[data-testid="assessment"]', { timeout: 30_000 });
await page.waitForTimeout(600);
await shot("assess");

await page.goto(`${base}/#/settings/posture`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="posture-list"]', { timeout: 10_000 }).catch(() => undefined);
await page.waitForTimeout(400);
await shot("posture");

await page.goto(`${base}/#/audit`, { waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="audit-table"]', { timeout: 10_000 }).catch(() => undefined);
await page.waitForTimeout(400);
await shot("audit");

await browser.close();
console.log("done:", out);
