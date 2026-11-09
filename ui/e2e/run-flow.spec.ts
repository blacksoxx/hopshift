import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../tests/fixtures/discovery_multi_vm.json");

const ADMIN = { username: "e2e-admin", password: "correct-horse-battery-staple-42", name: "E2E Admin" };

/** Create the first administrator when the server is fresh, otherwise sign in. */
async function signIn(page: Page) {
  await page.goto("/#/");
  await page.waitForURL(/#\/(setup|login|$)/, { timeout: 30_000 });
  if (page.url().includes("#/setup")) {
    await page.getByTestId("setup-username").fill(ADMIN.username);
    await page.getByTestId("setup-name").fill(ADMIN.name);
    await page.getByTestId("setup-password").fill(ADMIN.password);
    await page.getByTestId("setup-confirm").fill(ADMIN.password);
    await page.getByTestId("setup-submit").click();
  } else if (page.url().includes("#/login")) {
    await page.getByTestId("login-username").fill(ADMIN.username);
    await page.getByTestId("login-password").fill(ADMIN.password);
    await page.getByTestId("login-submit").click();
  }
  await expect(page.getByTestId("stat-runs")).toBeVisible({ timeout: 30_000 });
}

test.describe.configure({ mode: "serial" });

test("setup, create a run, review the CIM, approve twice, inspect artifacts and compliance", async ({ page }) => {
  await signIn(page);

  // ── wizard ────────────────────────────────────────────────────────────────
  await page.goto("/#/runs/new");
  await page.getByTestId("discovery-file").setInputFiles(FIXTURE);
  await expect(page.getByTestId("discovery-summary")).toContainText("4");
  await page.getByTestId("wizard-next").click();

  await page.getByTestId("cloud-aws").click();
  await page.getByTestId("run-name").fill("e2e lab migration");
  await page.getByTestId("owner").fill("playwright");
  await page.getByTestId("run-tags").fill("e2e");
  await page.keyboard.press("Enter");
  // keep the flow offline and fast: no terraform/tflint, no model, no MCP
  await page.getByTestId("toggle-validation").click();
  await expect(page.getByTestId("toggle-validation")).toHaveAttribute("data-state", "unchecked");
  await expect(page.getByTestId("toggle-ai-notes")).toHaveAttribute("data-state", "unchecked");
  await page.getByTestId("wizard-next").click();

  await page.getByTestId("connection-none").click();
  await page.getByTestId("wizard-next").click();
  await page.getByTestId("start-run").click();

  // ── run detail: paused at review_cim ──────────────────────────────────────
  await expect(page).toHaveURL(/#\/runs\/\d{8}T\d{6}Z-[0-9a-f]{8}/);
  const banner = page.getByTestId("paused-banner");
  await expect(banner).toContainText("review_cim", { timeout: 60_000 });
  await expect(page.getByTestId("step-sizer")).toHaveAttribute("data-state", "done");

  await page.getByTestId("tab-overview").click();
  await expect(page.getByTestId("quarantine-table")).toContainText("Legacy App Server (RDM)");

  await page.getByTestId("tab-cim").click();
  const name = page.getByTestId("unit-name-0");
  await expect(name).toHaveValue("web-01");
  await name.fill("web-01-e2e");
  await page.getByTestId("save-cim").click();
  await expect(page.getByText("CIM saved into the paused run")).toBeVisible();

  // ── approve CIM → paused at approve_output ────────────────────────────────
  await page.getByTestId("approve").click();
  await expect(banner).toContainText("approve_output", { timeout: 60_000 });
  await page.getByTestId("tab-artifacts").click();
  await expect(page.getByText("No artifacts yet")).toBeVisible();

  // ── approve output → succeeded ────────────────────────────────────────────
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("status-badge").first()).toHaveText("succeeded", { timeout: 60_000 });

  await page.getByTestId("tab-artifacts").click();
  const edited = page.getByTestId("artifact-item").filter({ hasText: "compute_web-01-e2e.tf" });
  await expect(edited).toBeVisible();
  await edited.click();
  await expect(page.getByTestId("artifact-content")).toContainText('resource "aws_instance" "web_01_e2e"', { timeout: 15_000 });

  await page.getByTestId("tab-compliance").click();
  await expect(page.getByTestId("compliance-report")).toBeVisible();

  // ── list, dashboard, audit ────────────────────────────────────────────────
  await page.goto("/#/runs");
  await expect(page.getByTestId("run-row").first()).toContainText("e2e lab migration");
  await expect(page.getByTestId("run-row").first()).toContainText("succeeded");

  await page.goto("/#/audit");
  await expect(page.getByTestId("audit-table")).toContainText("run.approved");
});

test("connections: add an environment connection and open it", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/connections");
  await page.getByTestId("add-connection").click();
  await page.getByTestId("provider-aws").click();
  await page.getByTestId("method-environment").click();
  await page.getByTestId("connection-name").fill("aws-lab-env");
  await page.getByTestId("field-region").fill("eu-west-1");
  await page.getByTestId("connection-submit").click();
  // verification runs automatically; without credentials it fails, which must render cleanly
  await expect(page.getByTestId("connection-test-result")).toBeVisible({ timeout: 30_000 });
  await page.goto("/#/connections");
  await expect(page.getByTestId("connection-row").filter({ hasText: "aws-lab-env" })).toBeVisible();
});

test("assess page scores the inventory without a run", async ({ page }) => {
  await signIn(page);
  await page.goto("/#/assess");
  await page.getByTestId("discovery-file").setInputFiles(FIXTURE);
  await page.getByTestId("run-assess").click();
  await expect(page.getByTestId("assessment")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("assessment")).toContainText("RDM disk detected");
});

test("sign out and sign back in; a viewer cannot create runs", async ({ page }) => {
  await signIn(page);
  await page.getByTestId("user-menu").click();
  await page.getByTestId("logout").click();
  await expect(page.getByTestId("login-form")).toBeVisible();
  await page.getByTestId("login-username").fill(ADMIN.username);
  await page.getByTestId("login-password").fill("not the password");
  await page.getByTestId("login-submit").click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByTestId("login-password").fill(ADMIN.password);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("stat-runs")).toBeVisible({ timeout: 30_000 });
});
