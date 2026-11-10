import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authState, renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import { ProfilePanel } from "./ProfilePanel";

const mocks = vi.hoisted(() => ({ changePassword: vi.fn(), mfaEnroll: vi.fn(), mfaConfirm: vi.fn(), mfaDisable: vi.fn(), downloadText: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, changePassword: mocks.changePassword, mfaEnroll: mocks.mfaEnroll, mfaConfirm: mocks.mfaConfirm, mfaDisable: mocks.mfaDisable } };
});
vi.mock("@/lib/utils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/utils")>();
  return { ...actual, downloadText: mocks.downloadText };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

beforeEach(() => {
  resetAuth();
  Object.values(mocks).forEach((fn) => fn.mockReset());
  mocks.mfaEnroll.mockResolvedValue({ secret: "JBSWY3DPEHPK3PXP", otpauth_uri: "otpauth://totp/VMA:ada?secret=JBSWY3DPEHPK3PXP&issuer=VMA" });
  mocks.mfaConfirm.mockResolvedValue({ recovery_codes: ["aaaa-1111", "bbbb-2222", "cccc-3333"] });
});

describe("ProfilePanel", () => {
  it("shows the account card", async () => {
    renderWithProviders(<ProfilePanel />);
    const card = screen.getByTestId("profile-card");
    expect(card).toHaveTextContent("admin");
    expect(card).toHaveTextContent("local");
    expect(screen.getByTestId("mfa-status")).toHaveTextContent("not enrolled");
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("walks through MFA enrolment: QR, code, recovery codes, acknowledgement, refresh", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<ProfilePanel />);
    await user.click(screen.getByTestId("mfa-enable"));

    const code = await screen.findByTestId("mfa-code");
    expect(mocks.mfaEnroll).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("mfa-secret")).toHaveTextContent("JBSWY3DPEHPK3PXP");
    expect(screen.getByTestId("mfa-qr")).toBeInTheDocument();
    expect(screen.getByTestId("mfa-confirm")).toBeDisabled();

    await user.type(code, "123456");
    await user.click(screen.getByTestId("mfa-confirm"));
    await waitFor(() => expect(mocks.mfaConfirm).toHaveBeenCalledWith("123456"));

    const codes = await screen.findByTestId("recovery-codes");
    expect(codes).toHaveTextContent("aaaa-1111");
    expect(codes).toHaveTextContent("cccc-3333");
    const done = screen.getByTestId("mfa-done");
    expect(done).toBeDisabled();

    await user.click(screen.getByTestId("recovery-download"));
    expect(mocks.downloadText).toHaveBeenCalledWith("hopshift-recovery-codes.txt", "aaaa-1111\nbbbb-2222\ncccc-3333\n");

    await user.click(screen.getByTestId("recovery-saved"));
    expect(done).toBeEnabled();
    await user.click(done);
    await waitFor(() => expect(authState.refresh).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId("recovery-codes")).toBeNull());
  });

  it("keeps the dialog open and shows the error when the code is rejected", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.mfaConfirm.mockRejectedValue(new Error("invalid code"));
    renderWithProviders(<ProfilePanel />);
    await user.click(screen.getByTestId("mfa-enable"));
    await user.type(await screen.findByTestId("mfa-code"), "000000");
    await user.click(screen.getByTestId("mfa-confirm"));
    expect(await screen.findByText("invalid code")).toBeInTheDocument();
    expect(screen.getByTestId("mfa-code")).toBeInTheDocument();
  });

  it("opens enrolment automatically with ?enroll=1 and explains the policy", async () => {
    setAuthUser({ mfa_enrollment_required: true });
    renderWithProviders(<ProfilePanel />, { route: "/settings/profile?enroll=1" });
    expect(screen.getByTestId("mfa-required")).toHaveTextContent("second factor is required");
    expect(await screen.findByTestId("mfa-code")).toBeInTheDocument();
    expect(mocks.mfaEnroll).toHaveBeenCalledTimes(1);
  });

  it("disables MFA with password and code", async () => {
    const user = userEvent.setup({ delay: null });
    setAuthUser({ mfa_enabled: true });
    mocks.mfaDisable.mockResolvedValue(undefined);
    renderWithProviders(<ProfilePanel />);
    expect(screen.getByTestId("mfa-status")).toHaveTextContent("enabled");
    await user.click(screen.getByTestId("mfa-disable"));
    await user.type(await screen.findByTestId("mfa-disable-password"), "hunter2hunter2");
    await user.type(screen.getByTestId("mfa-disable-code"), "654321");
    await user.click(screen.getByTestId("mfa-disable-confirm"));
    await waitFor(() => expect(mocks.mfaDisable).toHaveBeenCalledWith("hunter2hunter2", "654321"));
    await waitFor(() => expect(authState.refresh).toHaveBeenCalled());
  });

  it("changes the password with the same policy as setup", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.changePassword.mockResolvedValue(undefined);
    renderWithProviders(<ProfilePanel />);
    await user.type(screen.getByTestId("password-current"), "old password 123");
    await user.type(screen.getByTestId("password-new"), "ada is here!");
    expect(screen.getByText(/must not contain the username/)).toBeInTheDocument();
    await user.clear(screen.getByTestId("password-new"));
    await user.type(screen.getByTestId("password-new"), "new long password!");
    await user.type(screen.getByTestId("password-confirm"), "new long password!");
    await user.click(screen.getByTestId("password-submit"));
    await waitFor(() => expect(mocks.changePassword).toHaveBeenCalledWith("old password 123", "new long password!"));
    await waitFor(() => expect(screen.getByTestId("password-new")).toHaveValue(""));
  });

  it("tells OIDC users the password lives with the identity provider", () => {
    setAuthUser({ auth_kind: "oidc" });
    renderWithProviders(<ProfilePanel />);
    expect(screen.getByTestId("password-oidc")).toHaveTextContent("identity provider");
    expect(screen.queryByTestId("password-form")).toBeNull();
    expect(screen.getByTestId("mfa-enable")).toBeInTheDocument();
  });

  it("degrades gracefully when accounts are disabled on the server", () => {
    setAuthUser({ id: "anonymous", username: "anonymous", name: "Local user", auth_kind: "disabled" });
    renderWithProviders(<ProfilePanel />);
    expect(screen.getByTestId("profile-unavailable")).toHaveTextContent("not available on this server");
    expect(screen.queryByTestId("mfa-enable")).toBeNull();
    expect(screen.queryByTestId("password-form")).toBeNull();
  });

  it("degrades gracefully when the MFA endpoint is missing", async () => {
    const user = userEvent.setup({ delay: null });
    const { ApiError } = await import("@/api");
    mocks.mfaEnroll.mockRejectedValue(new ApiError(404, "Not Found"));
    renderWithProviders(<ProfilePanel />);
    await user.click(screen.getByTestId("mfa-enable"));
    expect(await screen.findByTestId("mfa-unavailable")).toHaveTextContent("not available on this server");
  });
});
