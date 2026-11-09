import * as React from "react";
import { MemoryRouter } from "react-router-dom";
import { render, type RenderOptions } from "@testing-library/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Cim, ComputeUnit, RunRecord } from "@/types";

// Radix primitives touch a few browser APIs jsdom does not implement.
export function installDomPolyfills(): void {
  if (typeof window === "undefined") return;
  if (!("ResizeObserver" in window)) {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.defineProperty(window, "ResizeObserver", { value: ResizeObserverStub, configurable: true });
  }
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  if (!proto.scrollIntoView) proto.scrollIntoView = () => {};
  if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
  if (!proto.setPointerCapture) proto.setPointerCapture = () => {};
  if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
}

export function renderWithProviders(ui: React.ReactElement, options?: RenderOptions) {
  installDomPolyfills();
  return render(
    <MemoryRouter>
      <TooltipProvider>{ui}</TooltipProvider>
    </MemoryRouter>,
    options,
  );
}

export function makeRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    run_id: "20261109T120000Z-abcdef12",
    created_at: "2026-11-09T12:00:00+00:00",
    updated_at: "2026-11-09T12:05:00+00:00",
    status: "paused",
    cloud: "aws",
    mode: "deterministic",
    options: { cloud: "aws", environment: "dev", owner: "ui", skip_validation: true, skip_opa: false, no_mcp: true, dry_run: false, llm_review_notes: false, pause_points: ["review_cim", "approve_output"] },
    input_filename: "discovery.json",
    run_dir: "/tmp/runs/x",
    paused_before: "sizer",
    pause_point: "review_cim",
    error: null,
    event_count: 3,
    name: "First run",
    tags: ["demo"],
    connection_id: null,
    created_by: "tester",
    cancel_requested: false,
    executing: false,
    ...overrides,
  };
}

export function makeUnit(overrides: Partial<ComputeUnit> = {}): ComputeUnit {
  return {
    id: "vm-1",
    name: "web-01",
    vcpus: 2,
    ram_mb: 4096,
    migration_status: "migratable",
    blockers: [],
    cluster_ref: "prod-cluster",
    guest_os: "Ubuntu 22.04",
    image_ref: null,
    nics: [{ name: "nic0", port_group_ref: "pg-web" }],
    storage_volumes: [{ id: "disk-0", size_gb: 40, datastore: "ds1" }],
    ...overrides,
  };
}

export function makeCim(units?: ComputeUnit[]): Cim {
  return {
    source_vcenter: "vc01",
    source: { platform: "vsphere", name: "vc01", hostname: null },
    target_provider: "aws",
    network_topology: { distributed_switches: [{ name: "dvs0", port_groups: [{ name: "pg-web", vlan_id: "10" }] }] },
    clusters: [
      { name: "prod-cluster", semantics: "affinity" },
      { name: "db-cluster", semantics: "anti_affinity" },
    ],
    compute_units: units ?? [makeUnit(), makeUnit({ id: "vm-2", name: "db-01", vcpus: 8, ram_mb: 16384, cluster_ref: "db-cluster", migration_status: "blocked", blockers: ["rdm_disk_present"] })],
  };
}
