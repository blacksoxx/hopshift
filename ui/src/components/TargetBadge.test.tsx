import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, meta: vi.fn() } };
});

import { api } from "@/api";
import { renderWithProviders } from "@/test-utils";
import { resetMetaCache } from "@/lib/meta";
import { TIER_COPY, TargetBadge, TierBadge } from "./TargetBadge";
import type { Meta } from "@/types";

const META: Meta = {
  version: "0",
  clouds: ["aws", "proxmox"],
  targets: [
    { name: "aws", label: "Amazon Web Services", blurb: "EC2", tier: "tested", root: "aws-migration", tflint: true, connection_provider: "aws", architectures: ["x86_64"], docs: "" },
    { name: "proxmox", label: "Proxmox VE", blurb: "QEMU VMs", tier: "experimental", root: "proxmox-migration", tflint: false, connection_provider: "proxmox", architectures: ["x86_64"], docs: "" },
  ],
  sources: [],
  modes: [],
  pause_points: {},
  nodes: [],
  default_pause_points: [],
  auth_mode: "disabled",
  features: { connections: true, deployments: true, secrets: true },
};

describe("TargetBadge", () => {
  beforeEach(() => resetMetaCache());
  afterEach(() => vi.clearAllMocks());

  it("shows the registry label once /api/meta has answered, the bare name before", async () => {
    let resolve: (meta: Meta) => void = () => {};
    vi.mocked(api.meta).mockReturnValue(new Promise<Meta>((done) => (resolve = done)));
    renderWithProviders(<TargetBadge name="proxmox" />);
    expect(screen.getByTestId("target-badge")).toHaveTextContent("PROXMOX");
    resolve(META);
    await waitFor(() => expect(screen.getByTestId("target-badge")).toHaveTextContent("Proxmox VE"));
    expect(screen.getByTestId("target-badge")).toHaveAttribute("data-target", "proxmox");
  });

  it("falls back to the upper-cased name for targets the registry does not list", async () => {
    vi.mocked(api.meta).mockResolvedValue(META);
    renderWithProviders(<TargetBadge name="hyperv" />);
    await waitFor(() => expect(api.meta).toHaveBeenCalled());
    expect(screen.getByTestId("target-badge")).toHaveTextContent("HYPERV");
  });

  it("adds the tier badge when asked and the registry knows the target", async () => {
    vi.mocked(api.meta).mockResolvedValue(META);
    renderWithProviders(<TargetBadge name="aws" tier />);
    const tier = await screen.findByTestId("tier-badge");
    expect(tier).toHaveAttribute("data-tier", "tested");
    expect(tier).toHaveTextContent("tested");
  });
});

describe("TierBadge", () => {
  it("maps every tier to its badge variant", () => {
    expect(TIER_COPY.tested.variant).toBe("success");
    expect(TIER_COPY.validated.variant).toBe("info");
    expect(TIER_COPY.experimental.variant).toBe("warning");
    renderWithProviders(
      <>
        <TierBadge tier="validated" />
        <TierBadge tier="made-up" focusable={false} />
      </>,
    );
    const [validated, unknown] = screen.getAllByTestId("tier-badge");
    expect(validated).toHaveTextContent("validated");
    expect(validated).toHaveAttribute("tabindex", "0");
    expect(unknown).toHaveTextContent("made-up");
    expect(unknown).not.toHaveAttribute("tabindex");
  });
});
