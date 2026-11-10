import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { screen, waitFor, within } from "@testing-library/react";
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

const META: Meta = {
  version: "0",
  clouds: ["aws"],
  targets: [{ name: "aws", label: "Amazon Web Services", blurb: "EC2", tier: "tested", root: "aws-migration", tflint: true, connection_provider: "aws", architectures: ["x86_64"], docs: "" }],
  sources: [],
  modes: [],
  pause_points: {},
  nodes: [],
  default_pause_points: [],
  auth_mode: "disabled",
  features: { connections: true, deployments: true, secrets: true },
};

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
    expect(screen.getByTestId("secrets-warning")).toHaveTextContent("HOPSHIFT_SECRET_KEY");
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
    expect(empty).toHaveTextContent("No connections yet");
    expect(empty.querySelector("a[href*='docs/connections.md']")).not.toBeNull();
    expect(screen.getByTestId("add-connection-empty")).toBeInTheDocument();
  });
});

describe("providers the UI has no hand-written metadata for", () => {
  beforeAll(installDomPolyfills);
  afterEach(() => vi.clearAllMocks());

  // A target plugin (proxmox, say) registers its provider in the catalog; the UI must render it
  // without a code change: catalog label, monogram tile, generic identity summary, no env map.
  const PROXMOX = makeConnection({
    id: "c9",
    name: "pve-lab",
    provider: "proxmox",
    provider_label: "Proxmox VE",
    auth_method: "api_token",
    method_label: "API token",
    config: { host: "https://pve1.lab:8006", token_id: "root@pam!hopshift" },
    secret_fields: ["secret"],
    status: "ok",
    last_checked_at: "2026-11-09T09:00:00Z",
    last_check: { identity: { node: "pve1", version: "8.2.4", cluster: { name: "lab" } }, message: "" },
  });

  function setupProxmox(route: string) {
    role = "operator";
    vi.mocked(api.meta).mockResolvedValue(META);
    vi.mocked(api.connectionCatalog).mockResolvedValue(CATALOG);
    vi.mocked(api.listConnections).mockResolvedValue([VERIFIED, PROXMOX]);
    vi.mocked(api.getConnection).mockResolvedValue(PROXMOX);
    return renderWithProviders(
      <Routes>
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/connections/:connectionId" element={<ConnectionsPage />} />
      </Routes>,
      { route },
    );
  }

  it("lists the connection with the catalog label, a generic monogram and a generic identity", async () => {
    setupProxmox("/connections");
    const rows = await screen.findAllByTestId("connection-row");
    const row = rows.find((item) => item.textContent?.includes("pve-lab"));
    expect(row).toBeDefined();
    expect(row).toHaveTextContent("Proxmox VE · API token");
    expect(row).toHaveTextContent("pve1 · 8.2.4");
    const icon = within(row as HTMLElement).getByTestId("provider-icon-proxmox");
    expect(icon).toHaveAttribute("data-generic", "true");
    expect(icon).toHaveTextContent("Pr");
    const awsRow = rows.find((item) => item.textContent?.includes("lab") && !item.textContent?.includes("pve-lab")) as HTMLElement;
    expect(within(awsRow).getByTestId("provider-icon-aws")).not.toHaveAttribute("data-generic");
    // the filter chips use the catalog label for the unknown provider too
    expect(screen.getByTestId("filter-proxmox")).toHaveTextContent("Proxmox VE");
  });

  it("shows the detail page with the raw configuration and points at the target's documentation for Terraform", async () => {
    setupProxmox("/connections/c9");
    expect(await screen.findByTestId("connection-title")).toHaveTextContent("pve-lab");
    expect(screen.getByTestId("config-list")).toHaveTextContent("https://pve1.lab:8006");
    expect(screen.getByTestId("identity-list")).toHaveTextContent("pve1");
    expect(screen.getByTestId("terraform-env-unknown")).toHaveTextContent("see the target's documentation");
    expect(screen.queryByTestId("terraform-env")).not.toBeInTheDocument();
    expect(screen.getByTestId("detail-new-run")).toHaveAttribute("href", "/runs/new?cloud=proxmox&connection=c9");
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
