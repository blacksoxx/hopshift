import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { ComplianceTab, filterControls } from "./ComplianceTab";
import { renderWithProviders } from "./test-helpers";
import type { ComplianceControl, ComplianceReport } from "@/types";

const mocks = vi.hoisted(() => ({ compliance: vi.fn() }));

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, compliance: mocks.compliance } };
});

const CONTROLS: ComplianceControl[] = [
  { id: "VMA-ENC-001", title: "Disks are encrypted", level: "enforce", status: "fail", frameworks: { cis: ["2.2.1"], hipaa: ["164.312(a)(2)(iv)"] }, resources: ["aws_ebs_volume.web_01_disk_0"], messages: ["encrypted = false"], remediation: "Set encrypted = true." },
  { id: "VMA-TAG-001", title: "Required tags present", level: "enforce", status: "pass", frameworks: { soc2: ["CC6.1"] }, resources: ["aws_instance.web_01", "aws_instance.db_01"], messages: [] },
  { id: "VMA-NET-002", title: "No world-open SSH", level: "advisory", status: "advisory", frameworks: { cis: ["5.2"] }, resources: ["aws_security_group.web"], messages: ["0.0.0.0/0 on 22"] },
  { id: "VMA-KMS-001", title: "Customer managed keys", level: "advisory", status: "not_applicable", frameworks: {}, resources: [], messages: [] },
];

const REPORT: ComplianceReport = {
  generated_at: "2026-11-09T12:30:00+00:00",
  cloud: "aws",
  summary: { controls: 4, passed: 1, failed: 1, advisory: 1, not_applicable: 1 },
  controls: CONTROLS,
  frameworks: { cis: { pass: 0, fail: 1, advisory: 1 }, soc2: { pass: 1, fail: 0 } },
};

describe("filterControls", () => {
  it("filters by status, searches text and sorts failures first", () => {
    expect(filterControls(CONTROLS, "fail", "").map((item) => item.id)).toEqual(["VMA-ENC-001"]);
    expect(filterControls(CONTROLS, "all", "ssh").map((item) => item.id)).toEqual(["VMA-NET-002"]);
    expect(filterControls(CONTROLS, "all", "").map((item) => item.status)).toEqual(["fail", "advisory", "pass", "not_applicable"]);
    expect(filterControls(CONTROLS, "all", "aws_instance.db_01").map((item) => item.id)).toEqual(["VMA-TAG-001"]);
  });
});

describe("ComplianceTab", () => {
  beforeEach(() => {
    mocks.compliance.mockReset();
  });

  it("renders the summary, framework chips and expandable rows", async () => {
    mocks.compliance.mockResolvedValue(REPORT);
    renderWithProviders(<ComplianceTab runId="r1" />);
    expect(await screen.findByTestId("compliance-report")).toBeInTheDocument();
    expect(screen.getByTestId("compliance-failed")).toHaveTextContent("1");
    expect(screen.getByTestId("compliance-frameworks")).toHaveTextContent("CIS");
    expect(screen.getByTestId("compliance-frameworks")).toHaveTextContent("SOC 2");
    expect(screen.getAllByTestId("compliance-row")).toHaveLength(4);

    fireEvent.click(screen.getAllByTestId("compliance-row")[0]);
    const detail = await screen.findByTestId("compliance-detail");
    expect(detail).toHaveTextContent("encrypted = false");
    expect(detail).toHaveTextContent("aws_ebs_volume.web_01_disk_0");
    expect(detail).toHaveTextContent("Set encrypted = true.");
  });

  it("narrows the table with the search box", async () => {
    mocks.compliance.mockResolvedValue(REPORT);
    renderWithProviders(<ComplianceTab runId="r1" />);
    await screen.findByTestId("compliance-report");
    fireEvent.change(screen.getByTestId("compliance-search"), { target: { value: "tags" } });
    await waitFor(() => expect(screen.getAllByTestId("compliance-row")).toHaveLength(1));
    expect(screen.getByTestId("compliance-row")).toHaveAttribute("data-status", "pass");
  });

  it("shows the empty state on 404", async () => {
    const { ApiError } = await import("@/api");
    mocks.compliance.mockRejectedValue(new ApiError(404, "no compliance report for this run yet"));
    renderWithProviders(<ComplianceTab runId="r1" />);
    expect(await screen.findByTestId("compliance-empty")).toHaveTextContent("No compliance report yet");
    expect(screen.queryByTestId("compliance-report")).toBeNull();
  });

  it("surfaces other errors with a retry", async () => {
    const { ApiError } = await import("@/api");
    mocks.compliance.mockRejectedValue(new ApiError(500, "disk on fire"));
    renderWithProviders(<ComplianceTab runId="r1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("disk on fire");
  });
});
