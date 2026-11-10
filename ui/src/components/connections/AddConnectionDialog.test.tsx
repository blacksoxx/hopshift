import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, createConnection: vi.fn(), testConnection: vi.fn() } };
});

import { ApiError, api } from "@/api";
import { AddConnectionDialog } from "./AddConnectionDialog";
import { CATALOG, installDomPolyfills, makeConnection, renderWithProviders } from "./test-utils";

describe("AddConnectionDialog", () => {
  beforeAll(installDomPolyfills);
  afterEach(() => vi.clearAllMocks());

  it("walks provider, method and form; validates; sends secrets separately; tests automatically", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createConnection).mockResolvedValue(makeConnection({ id: "new1", name: "lab" }));
    vi.mocked(api.testConnection).mockResolvedValue({ ok: false, identity: {}, message: "InvalidClientTokenId: The security token included in the request is invalid.", checked_at: "2026-11-09T10:00:00Z" });
    const onCreated = vi.fn();
    renderWithProviders(<AddConnectionDialog open onOpenChange={() => {}} catalog={CATALOG} secretsAvailable existingNames={["Existing"]} onCreated={onCreated} />);

    expect(screen.getByTestId("provider-aws")).toBeInTheDocument();
    expect(screen.getByTestId("provider-azure")).toBeInTheDocument();
    await user.click(screen.getByTestId("provider-aws"));
    expect(screen.getByTestId("method-access_keys")).toHaveTextContent("terraform ready");
    expect(screen.getByTestId("method-access_keys")).toHaveTextContent("stores secrets");
    expect(screen.getByTestId("method-sso")).toHaveTextContent("device sign-in");
    await user.click(screen.getByTestId("method-access_keys"));

    // Required validation blocks the submit.
    await user.click(screen.getByTestId("connection-submit"));
    expect(api.createConnection).not.toHaveBeenCalled();
    expect(screen.getByText("Name is required.")).toBeInTheDocument();
    expect(screen.getByText("Access key ID is required.")).toBeInTheDocument();
    expect(screen.getByText("Secret access key is required.")).toBeInTheDocument();
    expect(screen.getByText("Region is required.")).toBeInTheDocument();
    expect(screen.queryByText("Session token is required.")).not.toBeInTheDocument();

    // Names must be unique (case-insensitive).
    await user.type(screen.getByTestId("connection-name"), "existing");
    await user.type(screen.getByTestId("field-access_key_id"), "AKIAEXAMPLE");
    await user.type(screen.getByTestId("field-secret_access_key"), "s3cret");
    await user.type(screen.getByTestId("field-region"), "eu-west-1");
    await user.click(screen.getByTestId("connection-submit"));
    expect(screen.getByText("A connection with this name already exists.")).toBeInTheDocument();
    expect(api.createConnection).not.toHaveBeenCalled();

    await user.clear(screen.getByTestId("connection-name"));
    await user.type(screen.getByTestId("connection-name"), "lab");
    await user.click(screen.getByTestId("connection-submit"));
    await waitFor(() => expect(api.createConnection).toHaveBeenCalledTimes(1));
    expect(api.createConnection).toHaveBeenCalledWith({
      name: "lab",
      provider: "aws",
      auth_method: "access_keys",
      config: { access_key_id: "AKIAEXAMPLE", region: "eu-west-1" },
      secret: { secret_access_key: "s3cret" },
    });

    const result = await screen.findByTestId("connection-test-result");
    expect(result).toHaveTextContent("Verification failed");
    expect(result).toHaveTextContent("InvalidClientTokenId");
    expect(api.testConnection).toHaveBeenCalledWith("new1");
    expect(onCreated).toHaveBeenCalledTimes(2);
    expect(onCreated.mock.calls[1][0]).toMatchObject({ id: "new1", status: "failed" });
    expect(screen.getByTestId("add-open")).toBeEnabled();
  });

  it("disables methods that store secrets when the server has no encryption key", async () => {
    const user = userEvent.setup();
    renderWithProviders(<AddConnectionDialog open onOpenChange={() => {}} catalog={CATALOG} secretsAvailable={false} existingNames={[]} onCreated={() => {}} />);
    await user.click(screen.getByTestId("provider-aws"));
    expect(screen.getByTestId("method-access_keys")).toBeDisabled();
    expect(screen.getByTestId("method-access_keys")).toHaveTextContent("needs HOPSHIFT_SECRET_KEY");
    expect(screen.getByTestId("method-environment")).toBeEnabled();
    expect(screen.getByTestId("method-sso")).toBeEnabled();
    await user.click(screen.getByTestId("method-environment"));
    expect(screen.getByTestId("field-region")).toBeInTheDocument();
  });

  it("shows API errors inline with a status-specific title", async () => {
    const user = userEvent.setup();
    vi.mocked(api.createConnection).mockRejectedValueOnce(new ApiError(409, "a connection named 'lab' already exists"));
    renderWithProviders(<AddConnectionDialog open onOpenChange={() => {}} catalog={CATALOG} secretsAvailable existingNames={[]} onCreated={() => {}} />);
    await user.click(screen.getByTestId("provider-aws"));
    await user.click(screen.getByTestId("method-environment"));
    await user.type(screen.getByTestId("connection-name"), "lab");
    await user.type(screen.getByTestId("field-region"), "eu-west-1");
    await user.click(screen.getByTestId("connection-submit"));
    const alert = await screen.findByTestId("add-error");
    expect(alert).toHaveTextContent("That name is already in use");
    expect(alert).toHaveTextContent("a connection named 'lab' already exists");
    expect(api.testConnection).not.toHaveBeenCalled();

    vi.mocked(api.createConnection).mockRejectedValueOnce(new ApiError(503, "no encryption key configured: set HOPSHIFT_SECRET_KEY (generate one with `vma secrets generate-key`)"));
    await user.click(screen.getByTestId("connection-submit"));
    await waitFor(() => expect(screen.getByTestId("add-error")).toHaveTextContent("Secrets cannot be stored"));
  });
});
