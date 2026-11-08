import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(here, "../../tests/fixtures/discovery_multi_vm.json");

test("create a run, review the CIM, approve twice, inspect artifacts", async ({ page }) => {
  await page.goto("/#/runs/new");

  await page.getByTestId("discovery-file").setInputFiles(FIXTURE);
  await expect(page.getByTestId("file-summary")).toContainText("4 VM(s)");
  await page.locator("#cloud").selectOption("aws");
  await page.locator("#environment").fill("e2e");
  await page.locator("#owner").fill("playwright");
  await page.getByLabel("skip validation").check();
  await page.getByLabel("no MCP").check();
  await page.getByLabel("AI review notes").uncheck(); // keep the flow offline and fast
  await page.getByTestId("start-run").click();

  await expect(page).toHaveURL(/#\/runs\/\d{8}T\d{6}Z-[0-9a-f]{8}$/);
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

  await page.getByTestId("approve").click();
  await expect(banner).toContainText("approve_output", { timeout: 60_000 });
  await page.getByTestId("tab-artifacts").click();
  await expect(page.getByText("No artifacts yet")).toBeVisible();

  await page.getByTestId("approve").click();
  await expect(page.getByTestId("status-badge").first()).toHaveText("succeeded", { timeout: 60_000 });

  await page.getByTestId("tab-artifacts").click();
  const edited = page.getByTestId("artifact-item").filter({ hasText: "compute_web-01-e2e.tf" });
  await expect(edited).toBeVisible();
  await edited.click();
  await expect(page.getByTestId("artifact-content")).toContainText('resource "aws_instance" "web_01_e2e"');

  await page.goto("/#/runs");
  await expect(page.getByTestId("run-row").first()).toContainText("succeeded");
});

test("assess page scores the inventory without a run", async ({ page }) => {
  await page.goto("/#/assess");
  await page.getByTestId("discovery-file").setInputFiles(FIXTURE);
  await page.getByTestId("run-assess").click();
  await expect(page.getByTestId("assessment")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("assessment")).toContainText("RDM disk detected");
});
