import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Meta, Role } from "@/types";

let role: Role = "viewer";
const ROLE_ORDER: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    loading: false,
    status: null,
    error: null,
    user: { id: "u1", username: role, name: role, role, auth_kind: "local", mfa_enabled: false },
    can: (minimum: Role) => ROLE_ORDER[role] >= ROLE_ORDER[minimum],
    refresh: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, meta: vi.fn(), connectionCatalog: vi.fn(), listConnections: vi.fn(), getConnection: vi.fn(), testConnection: vi.fn() } };
});

import { api } from "@/api";
import { ConnectionsPage } from "@/pages/ConnectionsPage";
import { CATALOG, installDomPolyfills, makeConnection, renderWithProviders } from "./test-utils";

const META: Meta = { version: "0", clouds: ["aws"], modes: [], pause_points: {}, nodes: [], default_pause_points: [], auth_mode: "disabled", features: { connections: true, deployments: true, secrets: true } };

const VERIFIED = makeConnection({
  status: "ok",
  last_checked_at: "2026-11-09T09:00:00Z",
  last_check: { identity: { account: "123456789012", arn: "arn:aws:iam::123456789012:user/lab", region: "eu-west-1" }, message: "" },
});

function setup(nextRole: Role, overrides: Partial<Meta["features"]> = {}, route = "/connections") {
  role = nextRole;
  vi.mocked(api.meta).mockResolvedValue({ ...META, features: { ...META.features, ...overrides } });
  vi.mocked(api.connectionCatalog).mockResolvedValue(CATALOG);
  vi.mocked(api.listConnections).mockResolvedValue([VERIFIED]);
  vi.mocked(api.getConnection).mockResolvedValue(VERIFIED);
  return renderWithProviders(
    <Routes>
      <Route path="/connections" element={<ConnectionsPage />} />
      <Route path="/connections/:connectionId" element={<ConnectionsPage />} />
    </Routes>,
    { route },
  );
}

describe("ConnectionsPage role gating", () => {
  beforeAll(installDomPolyfills);
  afterEach(() => vi.clearAllMocks());

  it("lets a viewer see the list and identity but no actions", async () => {
    setup("viewer");
    const row = await screen.findByTestId("connection-row");
    expect(row).toHaveTextContent("lab");
    expect(row).toHaveTextContent("Amazon Web Services · Access keys");
    expect(row).toHaveTextContent("arn:aws:iam::123456789012:user/lab");
    expect(row).toHaveTextContent("terraform ready");
    expect(screen.queryByTestId("add-connection")).not.toBeInTheDocument();
    expect(screen.queryByTestId("connection-actions")).not.toBeInTheDocument();
  });

  it("lets an operator test and start runs but not edit or delete", async () => {
    const user = userEvent.setup();
    setup("operator");
    await screen.findByTestId("connection-row");
    expect(screen.queryByTestId("add-connection")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("connection-actions"));
    expect(await screen.findByTestId("action-test")).toBeInTheDocument();
    expect(screen.getByTestId("action-run")).toHaveAttribute("href", "/runs/new?cloud=aws&connection=c1");
    expect(screen.queryByTestId("action-edit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("action-delete")).not.toBeInTheDocument();
  });

  it("gives an admin the add button and the edit and delete actions", async () => {
    const user = userEvent.setup();
    setup("admin");
    await screen.findByTestId("connection-row");
    expect(screen.getByTestId("add-connection")).toBeInTheDocument();
    await user.click(screen.getByTestId("connection-actions"));
    expect(await screen.findByTestId("action-test")).toBeInTheDocument();
    expect(screen.getByTestId("action-edit")).toBeInTheDocument();
    expect(screen.getByTestId("action-delete")).toBeInTheDocument();
  });

  it("warns when secrets cannot be stored", async () => {
    setup("viewer", { secrets: false });
    await screen.findByTestId("connection-row");
    expect(screen.getByTestId("secrets-warning")).toHaveTextContent("VMA_SECRET_KEY");
  });

  it("shows the empty state with the guide link when there are no connections", async () => {
    role = "admin";
    vi.mocked(api.meta).mockResolvedValue(META);
    vi.mocked(api.connectionCatalog).mockResolvedValue(CATALOG);
    vi.mocked(api.listConnections).mockResolvedValue([]);
    renderWithProviders(
      <Routes>
        <Route path="/connections" element={<ConnectionsPage />} />
      </Routes>,
      { route: "/connections" },
    );
    const empty = await screen.findByTestId("connections-empty");
    expect(empty).toHaveTextContent("No cloud connections yet");
    expect(empty.querySelector("a[href*='docs/connections.md']")).not.toBeNull();
    expect(screen.getByTestId("add-connection-empty")).toBeInTheDocument();
  });
});

describe("ConnectionDetail role gating", () => {
  beforeAll(installDomPolyfills);
  afterEach(() => vi.clearAllMocks());

  it("hides every mutation from a viewer", async () => {
    setup("viewer", {}, "/connections/c1");
    expect(await screen.findByTestId("connection-title")).toHaveTextContent("lab");
    expect(screen.getByTestId("connection-status")).toHaveTextContent("ok");
    expect(screen.getByTestId("identity-list")).toHaveTextContent("arn:aws:iam::123456789012:user/lab");
    expect(screen.getByTestId("terraform-env")).toHaveTextContent("AWS_SECRET_ACCESS_KEY");
    expect(screen.getByTestId("secret-secret_access_key")).toHaveTextContent("set");
    expect(screen.queryByTestId("test-connection")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-new-run")).not.toBeInTheDocument();
    expect(screen.queryByTestId("name-edit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("replace-secret_access_key")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-edit-config")).not.toBeInTheDocument();
  });

  it("lets an operator test and offers device sign-in only for device-flow methods", async () => {
    const user = userEvent.setup();
    setup("operator", {}, "/connections/c1");
    await screen.findByTestId("connection-title");
    expect(screen.getByTestId("test-connection")).toBeInTheDocument();
    expect(screen.getByTestId("detail-new-run")).toHaveAttribute("href", "/runs/new?cloud=aws&connection=c1");
    expect(screen.queryByTestId("device-signin")).not.toBeInTheDocument();
    expect(screen.queryByTestId("detail-actions")).not.toBeInTheDocument();
    expect(screen.queryByTestId("replace-secret_access_key")).not.toBeInTheDocument();

    vi.mocked(api.testConnection).mockResolvedValue({ ok: false, identity: {}, message: "InvalidClientTokenId: *** rejected", checked_at: "2026-11-09T10:00:00Z" });
    await user.click(screen.getByTestId("test-connection"));
    await waitFor(() => expect(screen.getByTestId("connection-status")).toHaveTextContent("failed"));
    expect(screen.getByTestId("test-result")).toHaveTextContent("InvalidClientTokenId");
  });

  it("shows the device sign-in trigger for an SSO connection", async () => {
    role = "operator";
    const sso = makeConnection({ id: "c2", name: "sso-lab", auth_method: "sso", method_label: "IAM Identity Center (SSO)", device_flow: true, has_secret: false, secret_fields: [], config: { start_url: "https://x.awsapps.com/start", sso_region: "eu-west-1", account_id: "1", role_name: "Admin", region: "eu-west-1" } });
    vi.mocked(api.meta).mockResolvedValue(META);
    vi.mocked(api.connectionCatalog).mockResolvedValue(CATALOG);
    vi.mocked(api.listConnections).mockResolvedValue([sso]);
    vi.mocked(api.getConnection).mockResolvedValue(sso);
    renderWithProviders(
      <Routes>
        <Route path="/connections/:connectionId" element={<ConnectionsPage />} />
      </Routes>,
      { route: "/connections/c2" },
    );
    await screen.findByTestId("connection-title");
    expect(screen.getByTestId("device-signin")).toBeInTheDocument();
    expect(screen.getByTestId("terraform-env")).toHaveTextContent("temporary");
  });

  it("gives an admin rename, secret replacement and delete", async () => {
    const user = userEvent.setup();
    setup("admin", {}, "/connections/c1");
    await screen.findByTestId("connection-title");
    expect(screen.getByTestId("name-edit")).toBeInTheDocument();
    expect(screen.getByTestId("replace-secret_access_key")).toBeInTheDocument();
    expect(screen.getByTestId("detail-edit-config")).toBeInTheDocument();
    await user.click(screen.getByTestId("detail-actions"));
    expect(await screen.findByTestId("delete-connection")).toBeInTheDocument();
    expect(screen.getByTestId("detail-edit")).toBeInTheDocument();
  });
});
