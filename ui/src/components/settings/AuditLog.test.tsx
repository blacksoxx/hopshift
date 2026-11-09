import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import type { AuditEntry } from "@/types";
import { AuditLog, EMPTY_FILTERS, PAGE_SIZE, buildAuditQuery } from "./AuditLog";

const mocks = vi.hoisted(() => ({ audit: vi.fn(), auditVerify: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, audit: mocks.audit, auditVerify: mocks.auditVerify } };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

function entry(id: number, patch: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id,
    ts: "2026-11-09T10:00:00.000+00:00",
    actor: "ada",
    actor_kind: "user",
    action: "run.approved",
    target_type: "run",
    target_id: "run-123",
    outcome: "success",
    ip: "10.0.0.5",
    user_agent: "Mozilla/5.0",
    details: { pause_point: "review_cim" },
    prev_hash: "0".repeat(64),
    hash: "abcdef1234567890".repeat(4),
    ...patch,
  };
}

beforeEach(() => {
  resetAuth();
  mocks.audit.mockReset();
  mocks.auditVerify.mockReset();
  mocks.audit.mockResolvedValue({ entries: [entry(1), entry(2, { action: "auth.login", outcome: "failure", actor_kind: "anonymous", target_type: null, target_id: null, details: {} })], total: 2 });
});

describe("buildAuditQuery", () => {
  it("omits empty filters and pages by fifty", () => {
    expect(buildAuditQuery(EMPTY_FILTERS, 0)).toEqual({ limit: PAGE_SIZE, offset: 0, action: undefined, actor: undefined, outcome: undefined, since: undefined });
    expect(buildAuditQuery({ action: " run.approved ", actor: "ada", outcome: "denied", since: "2026-11-01" }, 2)).toEqual({ limit: 50, offset: 100, action: "run.approved", actor: "ada", outcome: "denied", since: "2026-11-01" });
  });
});

describe("AuditLog", () => {
  it("renders the table and builds the query from the filter bar", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AuditLog />);
    const table = await screen.findByTestId("audit-table");
    expect(table).toHaveTextContent("run.approved");
    expect(table).toHaveTextContent("failure");
    expect(mocks.audit).toHaveBeenCalledWith({ limit: 50, offset: 0, action: undefined, actor: undefined, outcome: undefined, since: undefined });

    await user.type(screen.getByTestId("audit-filter-action"), "auth.login");
    await user.type(screen.getByTestId("audit-filter-actor"), "sam");
    fireEvent.change(screen.getByTestId("audit-filter-since"), { target: { value: "2026-11-01" } });
    await waitFor(() => expect(mocks.audit).toHaveBeenLastCalledWith({ limit: 50, offset: 0, action: "auth.login", actor: "sam", outcome: undefined, since: "2026-11-01" }));
  });

  it("filters by outcome", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AuditLog />);
    await screen.findByTestId("audit-table");
    await user.click(screen.getByTestId("audit-filter-outcome"));
    await user.click(await screen.findByRole("option", { name: "Denied" }));
    await waitFor(() => expect(mocks.audit).toHaveBeenLastCalledWith(expect.objectContaining({ outcome: "denied", offset: 0 })));
  });

  it("expands a row to show details and the hash chain", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<AuditLog />);
    await screen.findByTestId("audit-table");
    await user.click(screen.getAllByTestId("audit-row")[0]);
    const details = await screen.findByTestId("audit-details");
    expect(details).toHaveTextContent('"pause_point": "review_cim"');
    expect(details).toHaveTextContent("abcdef12…7890");
    expect(details.querySelector('[title="' + "abcdef1234567890".repeat(4) + '"]')).not.toBeNull();
  });

  it("verifies the chain and reports the result", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.auditVerify.mockResolvedValue({ ok: true, entries: 2, broken_at: null, message: "chain verified" });
    renderWithProviders(<AuditLog />);
    await screen.findByTestId("audit-table");
    await user.click(screen.getByTestId("audit-verify"));
    const result = await screen.findByTestId("audit-verify-result");
    expect(result).toHaveTextContent("Audit chain intact");
    expect(result).toHaveTextContent("2 entries checked");
    expect(screen.getByTestId("audit-export")).toHaveAttribute("href", "/api/audit/export");
  });

  it("reports a broken chain", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.auditVerify.mockResolvedValue({ ok: false, entries: 40, broken_at: 17, message: "hash mismatch" });
    renderWithProviders(<AuditLog />);
    await screen.findByTestId("audit-table");
    await user.click(screen.getByTestId("audit-verify"));
    const result = await screen.findByTestId("audit-verify-result");
    expect(result).toHaveTextContent("Audit chain broken");
    expect(result).toHaveTextContent("#17");
  });

  it("pages through results", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.audit.mockResolvedValue({ entries: Array.from({ length: 50 }, (_, index) => entry(index + 1)), total: 120 });
    renderWithProviders(<AuditLog />);
    await screen.findByTestId("audit-table");
    expect(screen.getByTestId("audit-range")).toHaveTextContent("Showing 1–50 of 120");
    expect(screen.getByTestId("audit-prev")).toBeDisabled();
    await user.click(screen.getByTestId("audit-next"));
    await waitFor(() => expect(mocks.audit).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })));
  });

  it("is admin only", async () => {
    setAuthUser({ role: "operator" });
    renderWithProviders(<AuditLog />);
    expect(await screen.findByTestId("audit-forbidden")).toBeInTheDocument();
    expect(mocks.audit).not.toHaveBeenCalled();
  });

  it("explains when the audit endpoints are missing", async () => {
    const { ApiError } = await import("@/api");
    mocks.audit.mockRejectedValue(new ApiError(404, "Not Found"));
    renderWithProviders(<AuditLog />);
    expect(await screen.findByTestId("audit-unavailable")).toHaveTextContent("not available on this server");
  });
});
