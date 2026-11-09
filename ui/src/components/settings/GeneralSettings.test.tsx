import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, resetAuth, setAuthUser } from "@/test-utils";
import type { SettingSpec, SettingsPayload } from "@/types";
import { GeneralSettings, changedValues, controlValue, groupSchema } from "./GeneralSettings";

const mocks = vi.hoisted(() => ({ settings: vi.fn(), updateSettings: vi.fn() }));
vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, settings: mocks.settings, updateSettings: mocks.updateSettings } };
});
vi.mock("@/providers/AuthProvider", async () => (await import("@/test-utils")).authModule);

const schema: SettingSpec[] = [
  { key: "generation.mode", type: "choice", label: "Generation mode", help: "How Terraform is produced.", group: "Generation", options: ["deterministic", "llm", "hybrid"], minimum: null, maximum: null },
  { key: "validation.run_opa", type: "boolean", label: "OPA policies", help: "Evaluate policies.", group: "Validation", options: [], minimum: null, maximum: null },
  { key: "security.auth.session_hours", type: "integer", label: "Session lifetime (hours)", help: "Absolute expiry.", group: "Security", options: [], minimum: 1, maximum: 168 },
  { key: "llm.models.anthropic", type: "string", label: "Anthropic model", help: "Model id.", group: "AI", options: [], minimum: null, maximum: null },
  { key: "runtime.default_pause_points", type: "list", label: "Default pause points", help: "Where runs pause.", group: "Runs", options: ["review_cim", "approve_output"], minimum: null, maximum: null },
];

const payload: SettingsPayload = {
  effective: { "generation.mode": "deterministic", "validation.run_opa": false, "security.auth.session_hours": 12, "llm.models.anthropic": "claude-opus-5", "runtime.default_pause_points": ["review_cim"] },
  overrides: { "validation.run_opa": false },
  schema,
};

beforeEach(() => {
  resetAuth();
  mocks.settings.mockReset();
  mocks.updateSettings.mockReset();
  mocks.settings.mockResolvedValue(payload);
  mocks.updateSettings.mockImplementation(async (values: Record<string, unknown>) => ({ ...payload, effective: { ...payload.effective, ...values }, overrides: { ...payload.overrides, ...values } }));
});

describe("settings helpers", () => {
  it("shapes effective values for their controls", () => {
    expect(controlValue(schema[1], "true")).toBe(true);
    expect(controlValue(schema[2], 12)).toBe("12");
    expect(controlValue(schema[2], null)).toBe("");
    expect(controlValue(schema[4], undefined)).toEqual([]);
    expect(controlValue(schema[3], 0.5)).toBe("0.5");
  });

  it("returns only the keys that changed, typed for the API", () => {
    const draft = { "generation.mode": "deterministic", "security.auth.session_hours": "24", "validation.run_opa": true, "runtime.default_pause_points": ["review_cim"] };
    expect(changedValues(schema, payload.effective, draft)).toEqual({ "security.auth.session_hours": 24, "validation.run_opa": true });
  });

  it("groups the schema in first-seen order", () => {
    expect(groupSchema(schema).map((item) => item.group)).toEqual(["Generation", "Validation", "Security", "AI", "Runs"]);
  });
});

describe("GeneralSettings", () => {
  it("renders every schema type and sends only the changed keys", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<GeneralSettings />);

    expect(await screen.findByTestId("setting-generation.mode")).toHaveTextContent("deterministic");
    const toggle = screen.getByTestId("setting-validation.run_opa");
    expect(toggle).toHaveAttribute("data-state", "unchecked");
    const hours = screen.getByTestId("setting-security.auth.session_hours");
    expect(hours).toHaveValue(12);
    expect(hours).toHaveAttribute("min", "1");
    expect(hours).toHaveAttribute("max", "168");
    expect(screen.getByTestId("setting-llm.models.anthropic")).toHaveValue("claude-opus-5");
    const list = screen.getByTestId("setting-runtime.default_pause_points");
    expect(within(list).getByTestId("setting-runtime.default_pause_points-review_cim")).toHaveAttribute("data-state", "checked");
    expect(within(list).getByTestId("setting-runtime.default_pause_points-approve_output")).toHaveAttribute("data-state", "unchecked");

    const save = screen.getByTestId("settings-save");
    expect(save).toBeDisabled();

    await user.clear(hours);
    await user.type(hours, "24");
    await user.click(toggle);
    // touched but unchanged: must not be sent
    await user.click(within(list).getByTestId("setting-runtime.default_pause_points-approve_output"));
    await user.click(within(list).getByTestId("setting-runtime.default_pause_points-approve_output"));

    expect(screen.getByTestId("settings-dirty")).toHaveTextContent("2 unsaved changes");
    expect(save).toBeEnabled();
    await user.click(save);

    await waitFor(() => expect(mocks.updateSettings).toHaveBeenCalledTimes(1));
    expect(mocks.updateSettings).toHaveBeenCalledWith({ "security.auth.session_hours": 24, "validation.run_opa": true });
    await waitFor(() => expect(screen.getByTestId("settings-save")).toBeDisabled());
    expect(screen.getByTestId("settings-dirty")).toHaveTextContent("No unsaved changes");
  });

  it("blocks saving an integer outside its range", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<GeneralSettings />);
    const hours = await screen.findByTestId("setting-security.auth.session_hours");
    await user.clear(hours);
    await user.type(hours, "999");
    expect(screen.getByTestId("settings-save")).toBeDisabled();
    expect(screen.getByTestId("settings-dirty")).toHaveTextContent("Fix the highlighted numbers");
    expect(mocks.updateSettings).not.toHaveBeenCalled();
  });

  it("marks overridden keys and resets them by sending null", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithProviders(<GeneralSettings />);
    expect(await screen.findByTestId("setting-validation.run_opa-overridden")).toHaveTextContent("overridden");
    expect(screen.queryByTestId("setting-generation.mode-overridden")).toBeNull();
    await user.click(screen.getByTestId("setting-validation.run_opa-reset"));
    await waitFor(() => expect(mocks.updateSettings).toHaveBeenCalledWith({ "validation.run_opa": null }));
  });

  it("shows an inline error when the API rejects the change", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.updateSettings.mockRejectedValue(new Error("security.auth.session_hours must be at most 168"));
    renderWithProviders(<GeneralSettings />);
    const hours = await screen.findByTestId("setting-security.auth.session_hours");
    await user.clear(hours);
    await user.type(hours, "48");
    await user.click(screen.getByTestId("settings-save"));
    expect(await screen.findByTestId("settings-error")).toHaveTextContent("must be at most 168");
  });

  it("is read-only for non-administrators", async () => {
    setAuthUser({ role: "operator" });
    renderWithProviders(<GeneralSettings />);
    expect(await screen.findByText("Read only")).toBeInTheDocument();
    expect(screen.getByTestId("setting-security.auth.session_hours")).toBeDisabled();
    expect(screen.getByTestId("setting-validation.run_opa")).toBeDisabled();
    expect(screen.queryByTestId("settings-save")).toBeNull();
    expect(screen.queryByTestId("setting-validation.run_opa-reset")).toBeNull();
  });

  it("explains when the settings cannot be loaded", async () => {
    mocks.settings.mockRejectedValue(new Error("forbidden"));
    renderWithProviders(<GeneralSettings />);
    expect(await screen.findByTestId("settings-unavailable")).toHaveTextContent("forbidden");
  });
});
