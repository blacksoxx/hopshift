import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { DeployTab, variablePayload } from "./DeployTab";
import { makeRun, renderWithProviders } from "./test-helpers";
import type { Connection, Deployment, TerraformVariable } from "@/types";

const mocks = vi.hoisted(() => ({
  listDeployments: vi.fn(),
  createDeployment: vi.fn(),
  deployVariables: vi.fn(),
  setDeployVariables: vi.fn(),
  deployState: vi.fn(),
  deploymentLog: vi.fn(),
  deploymentPlan: vi.fn(),
  cancelDeployment: vi.fn(),
  subscribeDeploymentLog: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      listDeployments: mocks.listDeployments,
      createDeployment: mocks.createDeployment,
      deployVariables: mocks.deployVariables,
      setDeployVariables: mocks.setDeployVariables,
      deployState: mocks.deployState,
      deploymentLog: mocks.deploymentLog,
      deploymentPlan: mocks.deploymentPlan,
      cancelDeployment: mocks.cancelDeployment,
    },
    subscribeDeploymentLog: mocks.subscribeDeploymentLog,
  };
});

vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: mocks.toast }) }));

const RUN = makeRun({ status: "succeeded", paused_before: null, pause_point: null, connection_id: "c1" });

const CONNECTIONS: Connection[] = [
  { id: "c1", name: "aws-dev", provider: "aws", auth_method: "access_keys", config: {}, status: "ok", last_checked_at: null, last_check: null, created_by: null, created_at: "", updated_at: "", has_secret: true, secret_fields: [], terraform_ready: true },
  { id: "c2", name: "azure-prod", provider: "azure", auth_method: "service_principal", config: {}, status: "ok", last_checked_at: null, last_check: null, created_by: null, created_at: "", updated_at: "", has_secret: true, secret_fields: [], terraform_ready: true },
];

const PLAN: Deployment = {
  id: "p1",
  run_id: RUN.run_id,
  action: "plan",
  status: "succeeded",
  connection_id: "c1",
  connection_name: "aws-dev",
  provider: "aws",
  requested_by: "tester",
  approved_by: null,
  plan_id: null,
  created_at: "2026-11-09T12:10:00+00:00",
  started_at: "2026-11-09T12:10:01+00:00",
  finished_at: "2026-11-09T12:10:30+00:00",
  exit_code: 2,
  summary: { add: 3, change: 1, destroy: 0, replace: 0, resources: [{ address: "aws_instance.web_01", type: "aws_instance", actions: ["create"] }] },
  error: null,
};

const VARIABLES: TerraformVariable[] = [
  { name: "aws_region", type: "string", description: "Region", default: "us-east-1", sensitive: false, required: false, set: false, value: null },
  { name: "enable_monitoring", type: "bool", description: "", default: false, sensitive: false, required: false, set: false, value: null },
  { name: "image_overrides", type: "map(string)", description: "", default: {}, sensitive: false, required: false, set: false, value: null },
  { name: "db_password", type: "string", description: "", default: null, sensitive: true, required: true, set: true, value: "***" },
];

describe("DeployTab", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((fn) => fn.mockReset());
    mocks.listDeployments.mockResolvedValue([PLAN]);
    mocks.deployVariables.mockResolvedValue(VARIABLES);
    mocks.setDeployVariables.mockImplementation(async (_run: string, values: Record<string, unknown>) => VARIABLES.map((item) => (item.name in values ? { ...item, set: true, value: values[item.name] } : item)));
    mocks.deployState.mockResolvedValue({ exists: false, remote: false });
    mocks.deploymentLog.mockResolvedValue({ lines: ["Terraform has been successfully initialized!", "Plan: 3 to add, 1 to change, 0 to destroy."], next: 2, done: true });
    mocks.subscribeDeploymentLog.mockReturnValue(() => undefined);
    mocks.createDeployment.mockImplementation(async (_run: string, body: { action: string }) => ({ ...PLAN, id: "d2", action: body.action, status: "queued", summary: null, started_at: null, finished_at: null }));
  });

  it("gates apply behind a typed confirmation and sends plan id and connection", async () => {
    renderWithProviders(<DeployTab run={RUN} connections={CONNECTIONS} connectionsEnabled canOperate />);
    await waitFor(() => expect(screen.getByTestId("deploy-apply")).toBeEnabled());
    expect(screen.getAllByTestId("deployment-row")).toHaveLength(1);
    expect(await screen.findByTestId("deployment-log")).toHaveTextContent("successfully initialized");

    fireEvent.click(screen.getByTestId("deploy-apply"));
    const confirm = await screen.findByTestId("deploy-confirm");
    expect(confirm).toBeDisabled();
    expect(screen.getByTestId("deploy-confirm-summary")).toHaveTextContent("3");

    fireEvent.change(screen.getByTestId("deploy-confirm-input"), { target: { value: "nope" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByTestId("deploy-confirm-input"), { target: { value: RUN.run_id } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(mocks.createDeployment).toHaveBeenCalledTimes(1));
    expect(mocks.createDeployment).toHaveBeenCalledWith(RUN.run_id, { action: "apply", connection_id: "c1", plan_id: "p1", confirmation: RUN.run_id });
    await waitFor(() => expect(screen.queryByTestId("deploy-confirm")).toBeNull());
  });

  it("disables apply when there is no succeeded plan and lists only same-cloud connections", async () => {
    mocks.listDeployments.mockResolvedValue([]);
    renderWithProviders(<DeployTab run={RUN} connections={CONNECTIONS} connectionsEnabled canOperate />);
    await waitFor(() => expect(screen.getByTestId("deploy-plan")).toBeEnabled());
    expect(screen.getByTestId("deploy-apply")).toBeDisabled();
    expect(screen.getByTestId("deploy-connection")).toHaveTextContent("aws-dev");
    expect(screen.getByTestId("deploy-connection")).not.toHaveTextContent("azure-prod");

    fireEvent.click(screen.getByTestId("deploy-plan"));
    await waitFor(() => expect(mocks.createDeployment).toHaveBeenCalledWith(RUN.run_id, { action: "plan", connection_id: "c1", plan_id: undefined, confirmation: undefined }));
  });

  it("warns when the cloud has no connection and keeps the actions disabled", async () => {
    renderWithProviders(<DeployTab run={RUN} connections={[CONNECTIONS[1]]} connectionsEnabled canOperate />);
    expect(await screen.findByTestId("deploy-no-connection")).toHaveTextContent("No AWS connection yet");
    expect(screen.getByTestId("deploy-plan")).toBeDisabled();
    expect(screen.getByTestId("deploy-destroy")).toBeDisabled();
  });

  it("shows a clear alert when the API refuses with 403", async () => {
    const { ApiError } = await import("@/api");
    mocks.createDeployment.mockRejectedValue(new ApiError(403, "terraform destroy is disabled (deploy.allow_destroy)"));
    renderWithProviders(<DeployTab run={RUN} connections={CONNECTIONS} connectionsEnabled canOperate />);
    await waitFor(() => expect(screen.getByTestId("deploy-destroy")).toBeEnabled());
    fireEvent.click(screen.getByTestId("deploy-destroy"));
    fireEvent.change(await screen.findByTestId("deploy-confirm-input"), { target: { value: RUN.run_id } });
    fireEvent.click(screen.getByTestId("deploy-confirm"));
    expect(await screen.findByTestId("deploy-gate-error")).toHaveTextContent("deploy.allow_destroy");
    expect(screen.queryByTestId("deploy-confirm")).toBeNull();
  });

  it("hides mutations from viewers", async () => {
    renderWithProviders(<DeployTab run={RUN} connections={CONNECTIONS} connectionsEnabled canOperate={false} />);
    await screen.findAllByTestId("deployment-row");
    expect(screen.getByTestId("deploy-plan")).toBeDisabled();
    expect(screen.getByTestId("deploy-apply")).toBeDisabled();
    expect(screen.queryByTestId("deploy-variables-save")).toBeNull();
  });

  it("saves only the changed variables with parsed types", async () => {
    renderWithProviders(<DeployTab run={RUN} connections={CONNECTIONS} connectionsEnabled canOperate />);
    const region = (await screen.findByLabelText("aws_region")) as HTMLInputElement;
    expect(region.value).toBe("us-east-1");
    expect(screen.getByTestId("var-set-db_password")).toBeInTheDocument();
    fireEvent.change(region, { target: { value: "eu-west-1" } });
    fireEvent.change(screen.getByLabelText("image_overrides"), { target: { value: '{"web-01": "ami-1"}' } });
    fireEvent.click(screen.getByLabelText("enable_monitoring"));
    fireEvent.click(screen.getByTestId("deploy-variables-save"));
    await waitFor(() => expect(mocks.setDeployVariables).toHaveBeenCalledWith(RUN.run_id, { aws_region: "eu-west-1", image_overrides: { "web-01": "ami-1" }, enable_monitoring: true }));
  });

  it("variablePayload unsets blanks, keeps blank secrets and rejects bad numbers", () => {
    const specs: TerraformVariable[] = [
      { name: "count", type: "number", description: "", default: 1, sensitive: false, required: false, set: true, value: 2 },
      { name: "secret", type: "string", description: "", default: null, sensitive: true, required: false, set: true, value: "***" },
      { name: "name", type: "string", description: "", default: null, sensitive: false, required: false, set: true, value: "x" },
    ];
    const original = { count: "2", secret: "", name: "x" };
    expect(variablePayload(specs, { count: "5", secret: "", name: "" }, original)).toEqual({ count: 5, name: null });
    expect(variablePayload(specs, { count: "2", secret: "hunter2", name: "x" }, original)).toEqual({ secret: "hunter2" });
    expect(() => variablePayload(specs, { count: "many", secret: "", name: "x" }, original)).toThrow(/number/);
  });
});
