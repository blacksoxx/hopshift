import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RunEvent, RunRecord, RunState } from "../types";

const mocks = vi.hoisted(() => ({
  getRun: vi.fn(), events: vi.fn(), getState: vi.fn(), meta: vi.fn(), resume: vi.fn(), patchState: vi.fn(), artifacts: vi.fn(), rerun: vi.fn(),
}));

vi.mock("../api", () => ({
  api: mocks,
  subscribeEvents: vi.fn(() => () => undefined),
  TERMINAL_STATUSES: new Set(["succeeded", "failed", "error"]),
}));

import { RunDetailPage } from "./RunDetailPage";

const NODES = ["ingest", "blocker_parser", "enricher", "cim_mapper", "sizer", "mcp_client", "hcl_generator", "validator", "reporter"];

function record(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: "r1", created_at: "2026-11-06T10:00:00+00:00", updated_at: "", status: "paused", cloud: "aws", mode: "deterministic",
    options: { cloud: "aws", environment: "dev", owner: "o", skip_validation: true, skip_opa: false, no_mcp: true, dry_run: false, pause_points: ["review_cim"] },
    input_filename: "lab.json", run_dir: "", paused_before: "hcl_generator", pause_point: "review_cim", error: null, event_count: 5, executing: false,
    ...overrides,
  };
}

function state(): RunState {
  return {
    run_id: "r1", status: "paused", next: ["hcl_generator"],
    values: {
      sized_cim: {
        source_vcenter: "vc", source: { platform: "vmware_vsphere", name: "vc", hostname: null }, target_provider: "aws",
        network_topology: { distributed_switches: [{ name: "dvs-prod", port_groups: [{ name: "pg-web", vlan_id: "110" }] }] },
        clusters: [{ name: "prod", semantics: "unknown" }],
        compute_units: [
          { id: "1", name: "web-01", vcpus: 2, ram_mb: 8192, migration_status: "ready", blockers: [], cluster_ref: "prod", guest_os: "Ubuntu", nics: [{ name: "n", port_group_ref: "pg-web" }], storage_volumes: [{ id: "d", size_gb: 40, datastore: "ds" }] },
        ],
      },
      quarantine_queue: [{ compute_unit_id: "3", compute_unit_name: "legacy", reasons: ["rdm_disk"], stage: "blocker_parser" }],
    },
  };
}

const EVENTS: RunEvent[] = [
  { ts: "2026-11-06T10:00:00+00:00", type: "start", node: null, summary: {}, messages: [] },
  ...["ingest", "blocker_parser", "enricher", "cim_mapper", "sizer", "mcp_client"].map((node) => ({ ts: "2026-11-06T10:00:01+00:00", type: "node" as const, node, summary: { compute_units: 1, quarantined: 1, hcl_files: 0 }, messages: [`${node}: ok`] })),
  { ts: "2026-11-06T10:00:02+00:00", type: "paused", node: "hcl_generator", summary: { pause_point: "review_cim" }, messages: [] },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/runs/r1"]}>
      <Routes><Route path="/runs/:runId" element={<RunDetailPage />} /></Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getRun.mockResolvedValue(record());
  mocks.events.mockResolvedValue(EVENTS);
  mocks.getState.mockResolvedValue(state());
  mocks.meta.mockResolvedValue({ clouds: ["aws"], modes: ["deterministic"], pause_points: { review_cim: "hcl_generator", approve_output: "reporter" }, nodes: NODES, default_pause_points: [] });
  mocks.resume.mockResolvedValue({ status: "running" });
  mocks.patchState.mockResolvedValue(record());
  mocks.artifacts.mockResolvedValue([]);
});

describe("RunDetailPage", () => {
  it("shows the paused banner, timeline and quarantine for a paused run", async () => {
    renderPage();

    expect(await screen.findByTestId("paused-banner")).toHaveTextContent("review_cim");
    expect(screen.getByTestId("step-sizer")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("step-hcl_generator")).toHaveAttribute("data-state", "paused");
    expect(screen.getByTestId("quarantine-table")).toHaveTextContent("legacy");
    expect(screen.getByTestId("approve")).toHaveTextContent("Approve and continue");
  });

  it("lets the operator edit a VM name in the CIM and saves it through patchState, then approves", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("paused-banner");

    await user.click(screen.getByTestId("tab-cim"));
    const nameInput = await screen.findByTestId("unit-name-0");
    await user.clear(nameInput);
    await user.type(nameInput, "web-01-edited");
    await user.click(screen.getByTestId("save-cim"));

    await waitFor(() => expect(mocks.patchState).toHaveBeenCalledTimes(1));
    const [runId, values] = mocks.patchState.mock.calls[0] as [string, { sized_cim: { compute_units: { name: string }[] } }];
    expect(runId).toBe("r1");
    expect(values.sized_cim.compute_units[0].name).toBe("web-01-edited");

    await user.click(screen.getByTestId("approve"));
    await waitFor(() => expect(mocks.resume).toHaveBeenCalledWith("r1"));
  });

  it("offers re-run from a node once the run is finished", async () => {
    mocks.getRun.mockResolvedValue(record({ status: "succeeded", paused_before: null, pause_point: null }));
    const user = userEvent.setup();
    renderPage();

    const select = await screen.findByTestId("rerun-node");
    await user.selectOptions(select, "validator");
    await user.click(screen.getByTestId("rerun"));

    await waitFor(() => expect(mocks.rerun).toHaveBeenCalledWith("r1", "validator"));
  });
});
