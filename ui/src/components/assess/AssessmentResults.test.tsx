import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import type { AssessmentResult } from "@/types";
import { assessmentToCsv, assessmentToMarkdown, exportFilename } from "./assessExport";
import { AssessmentResults, topFindings } from "./AssessmentResults";

const mocks = vi.hoisted(() => ({ downloadText: vi.fn() }));
vi.mock("@/lib/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/utils")>();
  return { ...actual, downloadText: mocks.downloadText };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

const result: AssessmentResult = {
  generated_at: "2026-11-09T10:00:00Z",
  source_vcenter: "vcenter-lab.example.internal",
  target_provider: "aws",
  summary: { total_resources: 3, safe: 1, caution: 1, elevated: 0, critical: 1 },
  resources: [
    { resource_type: "compute_unit", resource_id: "vm-101", resource_name: "web-01", risk_level: "safe", risk_score: 5, safe_to_migrate: true, reasons: [], missing_data: [], recommendations: [] },
    { resource_type: "compute_unit", resource_id: "vm-104", resource_name: "Legacy App Server (RDM)", risk_level: "critical", risk_score: 95, safe_to_migrate: false, reasons: ["RDM disk detected", "Powered off"], missing_data: ["guest_os"], recommendations: ["Convert RDM disks to VMDK before migration"] },
    { resource_type: "compute_unit", resource_id: "vm-102", resource_name: "db-01, primary", risk_level: "caution", risk_score: 40, safe_to_migrate: true, reasons: ['Snapshot "pre-upgrade" present'], missing_data: [], recommendations: ["Consolidate snapshots"] },
  ],
};

beforeEach(() => {
  resetAuth();
  mocks.downloadText.mockReset();
});

describe("assessment export", () => {
  it("writes CSV with quoting for commas and quotes", () => {
    const csv = assessmentToCsv(result);
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("resource_name,resource_type,resource_id,risk_level,risk_score,safe_to_migrate,reasons,recommendations,missing_data");
    expect(lines).toHaveLength(4);
    expect(csv).toContain('"db-01, primary"');
    expect(csv).toContain('"Snapshot ""pre-upgrade"" present"');
    expect(csv).toContain("RDM disk detected; Powered off");
  });

  it("writes a Markdown report with summary and resource tables", () => {
    const md = assessmentToMarkdown(result);
    expect(md).toContain("# Migration readiness assessment");
    expect(md).toContain("| critical | 1 |");
    expect(md).toContain("| Legacy App Server (RDM) | compute unit".replace(" unit", "_unit"));
    expect(md).toContain("RDM disk detected; Powered off");
    expect(exportFilename(result, "csv")).toBe("assessment-aws-2026-11-09.csv");
  });

  it("ranks the most common findings", () => {
    expect(topFindings(result.resources)).toEqual([
      { reason: "Powered off", count: 1 },
      { reason: "RDM disk detected", count: 1 },
      { reason: 'Snapshot "pre-upgrade" present', count: 1 },
    ]);
  });
});

describe("AssessmentResults", () => {
  it("shows the summary, reasons inline and the riskiest resources first", () => {
    renderWithProviders(<AssessmentResults result={result} cloud="aws" />);
    const container = screen.getByTestId("assessment");
    expect(container).toHaveTextContent("RDM disk detected");
    expect(screen.getByTestId("assess-stat-total")).toHaveTextContent("3");
    expect(screen.getByTestId("assess-stat-critical")).toHaveTextContent("1");
    const rows = screen.getAllByTestId("assessment-row");
    expect(rows.map((row) => row.getAttribute("data-risk"))).toEqual(["critical", "caution", "safe"]);
    expect(within(rows[0]).getByTestId("assess-safe")).toHaveTextContent("no");
    expect(screen.getByTestId("assess-findings")).toHaveTextContent("RDM disk detected");
    expect(screen.getByTestId("start-migration")).toHaveAttribute("href", "/runs/new?cloud=aws");
  });

  it("expands a row for recommendations and missing data", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AssessmentResults result={result} cloud="aws" />);
    expect(screen.queryByTestId("assessment-details")).toBeNull();
    await user.click(screen.getAllByTestId("assessment-row")[0]);
    const details = await screen.findByTestId("assessment-details");
    expect(details).toHaveTextContent("Convert RDM disks to VMDK before migration");
    expect(details).toHaveTextContent("guest_os");
  });

  it("filters by risk level and sorts by column", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AssessmentResults result={result} cloud="aws" />);
    await user.click(screen.getByTestId("assess-filter-safe"));
    expect(screen.getAllByTestId("assessment-row")).toHaveLength(1);
    expect(screen.getByTestId("assessment-row")).toHaveTextContent("web-01");
    await user.click(screen.getByTestId("assess-filter-all"));
    expect(screen.getAllByTestId("assessment-row")).toHaveLength(3);
    // numeric columns sort descending first, then ascending
    await user.click(screen.getByTestId("assess-sort-risk_score"));
    expect(screen.getAllByTestId("assessment-row").map((row) => row.getAttribute("data-risk"))).toEqual(["critical", "caution", "safe"]);
    await user.click(screen.getByTestId("assess-sort-risk_score"));
    expect(screen.getAllByTestId("assessment-row").map((row) => row.getAttribute("data-risk"))).toEqual(["safe", "caution", "critical"]);
    await user.click(screen.getByTestId("assess-sort-resource_name"));
    expect(screen.getAllByTestId("assessment-row")[0]).toHaveTextContent("db-01");
  });

  it("exports CSV and Markdown through downloadText", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AssessmentResults result={result} cloud="aws" />);
    await user.click(screen.getByTestId("export-csv"));
    expect(mocks.downloadText).toHaveBeenCalledWith("assessment-aws-2026-11-09.csv", expect.stringContaining("RDM disk detected"), "text/csv");
    await user.click(screen.getByTestId("export-md"));
    expect(mocks.downloadText).toHaveBeenCalledWith("assessment-aws-2026-11-09.md", expect.stringContaining("# Migration readiness assessment"), "text/markdown");
  });

  it("hides the migration shortcut from viewers", () => {
    setAuthUser({ role: "viewer" });
    renderWithProviders(<AssessmentResults result={result} cloud="gcp" />);
    expect(screen.queryByTestId("start-migration")).toBeNull();
    expect(screen.getByText("Readiness for GCP")).toBeInTheDocument();
  });
});
