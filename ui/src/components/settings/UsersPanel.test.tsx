import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ADMIN, renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import type { AuthUser } from "@/types";
import { UsersPanel } from "./UsersPanel";

const mocks = vi.hoisted(() => ({ listUsers: vi.fn(), createUser: vi.fn(), updateUser: vi.fn(), deleteUser: vi.fn(), resetUserMfa: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, ...mocks } };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

const operator: AuthUser = { id: "u-op", username: "sam", name: "Sam Operator", role: "operator", auth_kind: "local", mfa_enabled: true, disabled: false, last_login_at: null };

beforeEach(() => {
  resetAuth();
  Object.values(mocks).forEach((fn) => fn.mockReset());
  mocks.listUsers.mockResolvedValue([ADMIN, operator]);
});

describe("UsersPanel", () => {
  it("lists accounts for administrators and protects the caller's own row", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<UsersPanel />);
    expect(await screen.findByTestId("users-table")).toBeInTheDocument();
    const rows = screen.getAllByTestId("user-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("ada");
    expect(rows[0]).toHaveTextContent("you");
    expect(rows[1]).toHaveTextContent("operator");
    expect(rows[1]).toHaveTextContent("enabled");

    await user.click(screen.getAllByTestId("user-actions")[0]);
    const remove = await screen.findByTestId("user-delete");
    expect(remove).toHaveAttribute("data-disabled");
    expect(screen.getByTestId("user-toggle-disabled")).toHaveAttribute("data-disabled");
  });

  it("hides administration from other roles", async () => {
    setAuthUser({ role: "operator" });
    renderWithProviders(<UsersPanel />);
    expect(await screen.findByTestId("users-forbidden")).toHaveTextContent("Administrators manage users");
    expect(screen.queryByTestId("add-user")).toBeNull();
    expect(mocks.listUsers).not.toHaveBeenCalled();
  });

  it("creates a user with the policy-checked password", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.createUser.mockResolvedValue({ ...operator, id: "u-new", username: "nina" });
    renderWithProviders(<UsersPanel />);
    await screen.findByTestId("users-table");
    await user.click(screen.getByTestId("add-user"));
    await user.type(await screen.findByTestId("user-username"), "nina");
    await user.type(screen.getByTestId("user-password"), "short");
    expect(screen.getByTestId("user-submit")).toBeDisabled();
    expect(screen.getByText(/at least 12 characters/)).toBeInTheDocument();
    await user.clear(screen.getByTestId("user-password"));
    await user.type(screen.getByTestId("user-password"), "correct horse battery staple");
    await user.click(screen.getByTestId("user-submit"));
    await waitFor(() => expect(mocks.createUser).toHaveBeenCalledWith({ username: "nina", password: "correct horse battery staple", name: "nina", role: "viewer" }));
    await waitFor(() => expect(mocks.listUsers).toHaveBeenCalledTimes(2));
  });

  it("disables another account from the row menu", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.updateUser.mockResolvedValue({ ...operator, disabled: true });
    renderWithProviders(<UsersPanel />);
    await screen.findByTestId("users-table");
    await user.click(screen.getAllByTestId("user-actions")[1]);
    await user.click(await screen.findByTestId("user-toggle-disabled"));
    await waitFor(() => expect(mocks.updateUser).toHaveBeenCalledWith("u-op", { disabled: true }));
  });

  it("deletes after confirmation", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.deleteUser.mockResolvedValue(undefined);
    renderWithProviders(<UsersPanel />);
    await screen.findByTestId("users-table");
    await user.click(screen.getAllByTestId("user-actions")[1]);
    await user.click(await screen.findByTestId("user-delete"));
    expect(await screen.findByTestId("user-dialog")).toHaveAttribute("data-mode", "delete");
    await user.click(screen.getByTestId("user-submit"));
    await waitFor(() => expect(mocks.deleteUser).toHaveBeenCalledWith("u-op"));
  });

  it("explains when the server has no accounts module", async () => {
    const { ApiError } = await import("@/api");
    mocks.listUsers.mockRejectedValue(new ApiError(400, "authentication is disabled (security.auth.mode: disabled)"));
    renderWithProviders(<UsersPanel />);
    expect(await screen.findByTestId("users-unavailable")).toHaveTextContent("not available on this server");
  });
});
