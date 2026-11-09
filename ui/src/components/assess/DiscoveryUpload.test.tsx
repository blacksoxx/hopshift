import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test-utils";
import { DiscoveryUpload } from "./DiscoveryUpload";
import { parseDiscovery, summarizeDiscovery } from "./discovery";

const discovery = {
  metadata: { schema_name: "vmware-discovery-stage1", schema_version: "1.0.0", vcenters_queried: ["vc-a", "vc-b"] },
  virtual_machines: [
    { vm_name: "web-01", cluster: "prod", power_state: "poweredOn", migration_blocked: false, migration_blockers: [] },
    { vm_name: "legacy", cluster: "prod", power_state: "poweredOff", migration_blocked: true, migration_blockers: ["rdm_disk_present"] },
    { vm_name: "db-01", cluster: "data", power_state: "poweredOn" },
  ],
};

describe("discovery parsing", () => {
  it("summarises the inventory", () => {
    expect(summarizeDiscovery(discovery)).toEqual({ vms: 3, blocked: 1, poweredOff: 1, clusters: 2, vcenter: "vc-a +1", schema: "vmware-discovery-stage1", version: "1.0.0" });
  });

  it("rejects non-JSON, non-objects and empty inventories", () => {
    expect(() => parseDiscovery("{nope", "x.json", 5)).toThrow(/not valid JSON/);
    expect(() => parseDiscovery("[1,2]", "x.json", 5)).toThrow(/not a JSON object/);
    expect(() => parseDiscovery('{"virtual_machines": []}', "x.json", 5)).toThrow(/No virtual machines/);
  });
});

describe("DiscoveryUpload", () => {
  it("reads a file, reports the summary and hands over the payload", async () => {
    const user = userEvent.setup({ delay: null });
    const onChange = vi.fn();
    renderWithProviders(<DiscoveryUpload file={null} onChange={onChange} />);
    const file = new File([JSON.stringify(discovery)], "lab.json", { type: "application/json" });
    await user.upload(screen.getByTestId("discovery-file"), file);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    const loaded = onChange.mock.calls[0][0];
    expect(loaded.name).toBe("lab.json");
    expect(loaded.summary.vms).toBe(3);
    expect(loaded.payload.virtual_machines).toHaveLength(3);
  });

  it("shows the summary for a loaded file", () => {
    const loaded = parseDiscovery(JSON.stringify(discovery), "lab.json", 10);
    renderWithProviders(<DiscoveryUpload file={loaded} onChange={() => {}} />);
    const summary = screen.getByTestId("discovery-summary");
    expect(summary).toHaveTextContent("Virtual machines");
    expect(summary).toHaveTextContent("3");
    expect(summary).toHaveTextContent("vc-a +1");
    expect(summary).toHaveTextContent("1 powered off");
    expect(screen.getByTestId("dropzone")).toHaveTextContent("lab.json");
  });

  it("explains a broken file and clears the selection", async () => {
    const user = userEvent.setup({ delay: null });
    const onChange = vi.fn();
    renderWithProviders(<DiscoveryUpload file={null} onChange={onChange} />);
    await user.upload(screen.getByTestId("discovery-file"), new File(["{broken"], "bad.json", { type: "application/json" }));
    expect(await screen.findByTestId("discovery-error")).toHaveTextContent("not valid JSON");
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
