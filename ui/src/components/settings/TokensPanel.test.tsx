import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import type { ApiToken } from "@/types";
import { TokensPanel, allowedRoles, isExpired } from "./TokensPanel";

const mocks = vi.hoisted(() => ({ listTokens: vi.fn(), createToken: vi.fn(), deleteToken: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, ...mocks } };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

const token: ApiToken = { id: "tok-1", name: "ci-pipeline", role: "operator", created_at: "2026-11-01T10:00:00Z", expires_at: "2027-01-01T00:00:00Z", last_used_at: null };

beforeEach(() => {
  resetAuth();
  Object.values(mocks).forEach((fn) => fn.mockReset());
  mocks.listTokens.mockResolvedValue([token]);
});

describe("token helpers", () => {
  it("limits token roles to the caller's role or lower", () => {
    expect(allowedRoles("viewer")).toEqual(["viewer"]);
    expect(allowedRoles("operator")).toEqual(["viewer", "operator"]);
    expect(allowedRoles("admin")).toEqual(["viewer", "operator", "admin"]);
    expect(allowedRoles(undefined)).toEqual(["viewer"]);
  });

  it("detects expiry", () => {
    expect(isExpired(token, new Date("2026-12-01").getTime())).toBe(false);
    expect(isExpired(token, new Date("2027-02-01").getTime())).toBe(true);
    expect(isExpired({ ...token, expires_at: null })).toBe(false);
  });
});

describe("TokensPanel", () => {
  it("lists the caller's tokens", async () => {
    renderWithProviders(<TokensPanel />);
    expect(await screen.findByTestId("tokens-table")).toBeInTheDocument();
    expect(screen.getByTestId("token-row")).toHaveTextContent("ci-pipeline");
    expect(screen.getByTestId("token-row")).toHaveTextContent("never");
    expect(mocks.listTokens).toHaveBeenCalledWith(false);
  });

  it("shows a new token exactly once", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.createToken.mockResolvedValue({ id: "tok-2", token: "hs_s3cr3t_value" });
    renderWithProviders(<TokensPanel />);
    await screen.findByTestId("tokens-table");
    await user.click(screen.getByTestId("create-token"));
    await user.type(await screen.findByTestId("token-name"), "deploy bot");
    await user.type(screen.getByTestId("token-expires"), "30");
    await user.click(screen.getByTestId("token-submit"));

    expect(await screen.findByTestId("token-value")).toHaveTextContent("hs_s3cr3t_value");
    expect(mocks.createToken).toHaveBeenCalledWith("deploy bot", "admin", 30);
    expect(screen.getByText(/only time the token is shown/)).toBeInTheDocument();
    await user.click(screen.getByTestId("token-done"));
    await waitFor(() => expect(screen.queryByTestId("token-value")).toBeNull());
    await waitFor(() => expect(mocks.listTokens).toHaveBeenCalledTimes(2));
  });

  it("offers an operator only viewer and operator roles", async () => {
    const user = userEvent.setup({ delay: null });
    setAuthUser({ role: "operator" });
    renderWithProviders(<TokensPanel />);
    await screen.findByTestId("tokens-table");
    expect(screen.queryByTestId("tokens-all")).toBeNull();
    await user.click(screen.getByTestId("create-token"));
    const trigger = await screen.findByTestId("token-role");
    expect(trigger).toHaveTextContent("operator");
    await user.click(trigger);
    const options = await screen.findAllByRole("option");
    expect(options.map((item) => item.textContent)).toEqual(["viewer", "operator"]);
  });

  it("lets administrators switch to every user's tokens", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.listTokens.mockResolvedValue([{ ...token, username: "sam" }]);
    renderWithProviders(<TokensPanel />);
    await screen.findByTestId("tokens-table");
    await user.click(screen.getByTestId("tokens-all"));
    await waitFor(() => expect(mocks.listTokens).toHaveBeenLastCalledWith(true));
    expect(await screen.findByText("sam")).toBeInTheDocument();
  });

  it("revokes after confirmation", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.deleteToken.mockResolvedValue(undefined);
    renderWithProviders(<TokensPanel />);
    await screen.findByTestId("tokens-table");
    await user.click(screen.getByTestId("token-delete"));
    await user.click(await screen.findByTestId("confirm-delete-token"));
    await waitFor(() => expect(mocks.deleteToken).toHaveBeenCalledWith("tok-1"));
  });

  it("explains when tokens are unavailable on this server", async () => {
    const { ApiError } = await import("@/api");
    mocks.listTokens.mockRejectedValue(new ApiError(404, "Not Found"));
    renderWithProviders(<TokensPanel />);
    expect(await screen.findByTestId("tokens-unavailable")).toHaveTextContent("not available on this server");
  });
});
