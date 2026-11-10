import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, meta: vi.fn(), listConnections: vi.fn(), createRun: vi.fn() } };
});

import { api } from "@/api";
import { renderWithProviders } from "@/test-utils";
import { resetMetaCache } from "@/lib/meta";
import { NewRunPage, summarizeDiscovery } from "./NewRunPage";
import type { Connection, Meta } from "@/types";

const META: Meta = {
  version: "0",
  clouds: ["aws", "openstack", "proxmox"],
  targets: [
    { name: "aws", label: "Amazon Web Services", blurb: "EC2, EBS, VPC, security groups, placement groups", tier: "tested", root: "aws-migration", tflint: true, connection_provider: "aws", architectures: ["x86_64"], docs: "docs/targets/aws.md" },
    { name: "openstack", label: "OpenStack", blurb: "Nova, Cinder, Neutron networks", tier: "validated", root: "openstack-migration", tflint: false, connection_provider: "openstack", architectures: ["x86_64"], docs: "" },
    { name: "proxmox", label: "Proxmox VE", blurb: "QEMU virtual machines, bridges, ZFS volumes", tier: "experimental", root: "proxmox-migration", tflint: false, connection_provider: "proxmox", architectures: ["x86_64"], docs: "" },
  ],
  sources: [
    { name: "vmware", label: "VMware vSphere", blurb: "VMs, disks, port groups", schema_names: ["vmware-discovery-stage1", "vmware-discovery"], platform: "vmware_vsphere", tier: "tested", collector: "Ansible collection", docs: "" },
    { name: "hyperv", label: "Microsoft Hyper-V", blurb: "VMs and virtual switches", schema_names: ["hyperv-export"], platform: "hyperv", tier: "experimental", collector: "PowerShell module", docs: "" },
  ],
  modes: ["deterministic", "llm", "hybrid"],
  pause_points: { review_cim: "hcl_generator", approve_output: "reporter" },
  nodes: [],
  default_pause_points: ["review_cim", "approve_output"],
  auth_mode: "disabled",
  features: { connections: true, deployments: true, secrets: true },
};

const CONNECTIONS: Connection[] = [
  { id: "c1", name: "aws-lab", provider: "aws", auth_method: "environment", method_label: "Process environment", config: {}, status: "ok", last_checked_at: null, last_check: null, created_by: null, created_at: "", updated_at: "", has_secret: false, secret_fields: [], terraform_ready: true },
  { id: "c2", name: "pve-lab", provider: "proxmox", auth_method: "api_token", method_label: "API token", config: {}, status: "unverified", last_checked_at: null, last_check: null, created_by: null, created_at: "", updated_at: "", has_secret: true, secret_fields: ["secret"], terraform_ready: true },
];

const VMWARE = {
  metadata: { schema_name: "VMware-Discovery-Stage1", schema_version: "1.0.0", vcenters_queried: ["vc-a.lab", "vc-b.lab"] },
  virtual_machines: [
    { vm_name: "web-01", cluster: "prod", source_vcenter: "vc-a.lab", networks: [{ distributed_switch: "dvs-prod" }] },
    { vm_name: "db-01", cluster: "data", source_vcenter: "vc-b.lab" },
    { vm_name: "legacy", cluster: "prod" },
  ],
};

function discoveryFile(payload: unknown, name = "lab.json"): File {
  return new File([JSON.stringify(payload)], name, { type: "application/json" });
}

function setup(route = "/runs/new") {
  vi.mocked(api.meta).mockResolvedValue(META);
  vi.mocked(api.listConnections).mockResolvedValue(CONNECTIONS);
  return renderWithProviders(
    <Routes>
      <Route path="/runs/new" element={<NewRunPage />} />
    </Routes>,
    { route },
  );
}

describe("summarizeDiscovery", () => {
  it("reads the schema, counts workloads and clusters and names the origin without assuming a source", () => {
    expect(summarizeDiscovery(VMWARE)).toEqual({ schema: "VMware-Discovery-Stage1", units: 3, clusters: 2, origin: "vc-a.lab +1" });
    expect(summarizeDiscovery({ metadata: { schema_name: "x", source: "pve1" }, compute_units: [{ cluster_ref: "c1" }] })).toEqual({ schema: "x", units: 1, clusters: 1, origin: "pve1" });
    expect(summarizeDiscovery({ virtual_machines: [] })).toEqual({ schema: null, units: 0, clusters: 0, origin: null });
    expect(summarizeDiscovery(null)).toEqual({ schema: null, units: 0, clusters: 0, origin: null });
  });
});

describe("NewRunPage", () => {
  beforeEach(() => resetMetaCache());
  afterEach(() => vi.clearAllMocks());

  it("detects the source from metadata.schema_name (case-insensitively) and enables Continue", async () => {
    const user = userEvent.setup({ delay: null });
    setup();
    expect(screen.getByTestId("wizard-next")).toBeDisabled();
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile(VMWARE));
    const detected = await screen.findByTestId("source-detected");
    expect(detected).toHaveTextContent("VMware vSphere accepts this file");
    expect(detected).toHaveAttribute("data-source", "vmware");
    expect(within(detected).getByTestId("tier-badge")).toHaveAttribute("data-tier", "tested");
    const summary = screen.getByTestId("discovery-summary");
    expect(summary).toHaveTextContent("VMware vSphere");
    expect(summary).toHaveTextContent("3");
    expect(summary).toHaveTextContent("vc-a.lab +1");
    expect(screen.queryByTestId("source-unknown")).not.toBeInTheDocument();
    expect(screen.getByTestId("wizard-next")).toBeEnabled();
  });

  it("refuses a file no registered source accepts, naming the schema and the registered sources", async () => {
    const user = userEvent.setup({ delay: null });
    setup();
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile({ metadata: { schema_name: "nutanix-export" }, virtual_machines: [{ vm_name: "a" }] }));
    const alert = await screen.findByTestId("source-unknown");
    expect(alert).toHaveTextContent('No registered source accepts schema "nutanix-export"');
    expect(alert).toHaveTextContent("VMware vSphere (vmware-discovery-stage1, vmware-discovery)");
    expect(alert).toHaveTextContent("Microsoft Hyper-V (hyperv-export)");
    expect(screen.getByTestId("discovery-summary")).toHaveTextContent("unknown");
    expect(screen.getByTestId("wizard-next")).toBeDisabled();

    // a file without any schema name is refused too
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile({ virtual_machines: [{ vm_name: "a" }] }, "bare.json"));
    expect(await screen.findByTestId("source-unknown")).toHaveTextContent("declares no metadata.schema_name");
    expect(screen.getByTestId("wizard-next")).toBeDisabled();

    // and a file another source claims is accepted
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile({ metadata: { schema_name: "hyperv-export" }, virtual_machines: [{ vm_name: "a" }] }, "hv.json"));
    expect(await screen.findByTestId("source-detected")).toHaveTextContent("Microsoft Hyper-V");
    expect(screen.getByTestId("wizard-next")).toBeEnabled();
  });

  it("renders the target cards from the registry with their tier badges and keeps the cloud-<name> test ids", async () => {
    const user = userEvent.setup({ delay: null });
    setup();
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile(VMWARE));
    await screen.findByTestId("source-detected");
    await user.click(screen.getByTestId("wizard-next"));

    const cards = await screen.findByTestId("target-cards");
    expect(within(cards).getAllByRole("button")).toHaveLength(3);
    const aws = screen.getByTestId("cloud-aws");
    expect(aws).toHaveTextContent("Amazon Web Services");
    expect(aws).toHaveTextContent("EC2, EBS, VPC");
    expect(aws).toHaveAttribute("data-tier", "tested");
    expect(aws).toHaveAttribute("aria-pressed", "true"); // first registered target is the default
    expect(within(aws).getByTestId("tier-badge")).toHaveTextContent("tested");
    expect(within(screen.getByTestId("cloud-openstack")).getByTestId("tier-badge")).toHaveAttribute("data-tier", "validated");
    const proxmox = screen.getByTestId("cloud-proxmox");
    expect(proxmox).toHaveTextContent("Proxmox VE");
    expect(within(proxmox).getByTestId("tier-badge")).toHaveAttribute("data-tier", "experimental");
    expect(screen.getByTestId("tier-legend")).toBeInTheDocument();
    expect(screen.queryByText("Target cloud")).not.toBeInTheDocument();

    await user.click(proxmox);
    expect(proxmox).toHaveAttribute("aria-pressed", "true");
    expect(aws).toHaveAttribute("aria-pressed", "false");
  });

  it("preselects the target named in the URL, lists only its connections and names source and target in the review", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(api.createRun).mockResolvedValue({ run_id: "20261110T120000Z-abcdef12", name: "lab" } as never);
    setup("/runs/new?cloud=proxmox&connection=c2");
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile(VMWARE));
    await screen.findByTestId("source-detected");
    await user.click(screen.getByTestId("wizard-next"));

    expect(await screen.findByTestId("cloud-proxmox")).toHaveAttribute("aria-pressed", "true");
    await user.type(screen.getByTestId("owner"), "platform-team");
    await user.click(screen.getByTestId("wizard-next"));

    // connection step: proxmox connections only, the one from the URL preselected
    expect(await screen.findByTestId("connection-c2")).toBeInTheDocument();
    expect(screen.queryByTestId("connection-c1")).not.toBeInTheDocument();
    expect(screen.getByText(/Only connections for Proxmox VE are listed/)).toBeInTheDocument();
    await user.click(screen.getByTestId("wizard-next"));

    const review = await screen.findByTestId("review-summary");
    expect(review).toHaveTextContent("VMware vSphere · lab.json · 3 compute units · vc-a.lab +1");
    expect(review).toHaveTextContent("Proxmox VE · dev · platform-team");
    expect(review).toHaveTextContent("pve-lab");

    await user.click(screen.getByTestId("start-run"));
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.createRun).mock.calls[0][0]).toMatchObject({ input_filename: "lab.json", connection_id: "c2", options: { cloud: "proxmox", owner: "platform-team" } });
  });

  it("explains when the registry cannot be loaded instead of guessing targets", async () => {
    const user = userEvent.setup({ delay: null });
    vi.mocked(api.meta).mockRejectedValue(new Error("registry offline"));
    vi.mocked(api.listConnections).mockResolvedValue([]);
    renderWithProviders(
      <Routes>
        <Route path="/runs/new" element={<NewRunPage />} />
      </Routes>,
      { route: "/runs/new" },
    );
    await user.upload(screen.getByTestId("discovery-file"), discoveryFile(VMWARE));
    expect(await screen.findByTestId("source-registry-error")).toHaveTextContent("registry offline");
    expect(screen.getByTestId("wizard-next")).toBeDisabled();
  });
});
