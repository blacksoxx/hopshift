import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, resetAuth } from "@/test-utils";
import type { PostureCheck } from "@/types";
import { PosturePanel, countChecks, sortChecks } from "./PosturePanel";

const mocks = vi.hoisted(() => ({ posture: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, posture: mocks.posture } };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

const checks: PostureCheck[] = [
  { id: "transport.tls", title: "TLS in use", status: "warn", detail: "plain HTTP", frameworks: ["SOC2 CC6.7"] },
  { id: "auth.enforced", title: "Authentication enforced", status: "pass", detail: "auth mode is required", frameworks: ["SOC2 CC6.1", "CIS 6.3"] },
  { id: "secrets.key", title: "Secrets encryption key configured", status: "fail", detail: "VMA_SECRET_KEY missing", frameworks: ["HIPAA 164.312(a)(2)(iv)"] },
  { id: "audit.chain", title: "Audit log integrity", status: "pass", detail: "12 entries, chain verified", frameworks: ["SOC2 CC7.2"] },
];

beforeEach(() => {
  resetAuth();
  mocks.posture.mockReset();
  mocks.posture.mockResolvedValue({ checks });
});

describe("posture helpers", () => {
  it("orders fail, warn, pass and counts them", () => {
    expect(sortChecks(checks).map((check) => check.id)).toEqual(["secrets.key", "transport.tls", "auth.enforced", "audit.chain"]);
    expect(countChecks(checks)).toEqual({ pass: 2, warn: 1, fail: 1 });
  });
});

describe("PosturePanel", () => {
  it("summarises and lists the checks with framework references", async () => {
    renderWithProviders(<PosturePanel />);
    const list = await screen.findByTestId("posture-list");
    const items = screen.getAllByTestId("posture-check");
    expect(items.map((item) => item.getAttribute("data-status"))).toEqual(["fail", "warn", "pass", "pass"]);
    expect(list).toHaveTextContent("HIPAA 164.312(a)(2)(iv)");
    expect(screen.getByTestId("posture-pass")).toHaveTextContent("2");
    expect(screen.getByTestId("posture-warn")).toHaveTextContent("1");
    expect(screen.getByTestId("posture-fail")).toHaveTextContent("1");
    expect(screen.getByText(/not a certification/)).toBeInTheDocument();
  });

  it("offers a retry when the checks cannot be loaded", async () => {
    mocks.posture.mockRejectedValue(new Error("boom"));
    renderWithProviders(<PosturePanel />);
    expect(await screen.findByText("Could not load the posture checks")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
