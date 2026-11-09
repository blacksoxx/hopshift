import type * as React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { CIM_SAVED_MESSAGE, CimTab, validateCim } from "./CimTab";
import { makeCim, renderWithProviders } from "./test-helpers";
import type { Cim } from "@/types";

const mocks = vi.hoisted(() => ({
  patchState: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, patchState: mocks.patchState } };
});

vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ toast: mocks.toast }) }));

const RUN = "20261109T120000Z-abcdef12";

describe("CimTab", () => {
  beforeEach(() => {
    mocks.patchState.mockReset();
    mocks.toast.mockReset();
    mocks.patchState.mockResolvedValue({ run_id: RUN });
  });

  it("edits a unit name and saves it as sized_cim with the exact success toast", async () => {
    const onSaved = vi.fn();
    renderWithProviders(<CimTab runId={RUN} cim={makeCim()} editable onSaved={onSaved} />);

    const name = screen.getByTestId("unit-name-0") as HTMLInputElement;
    expect(name.value).toBe("web-01");
    expect(screen.getByTestId("save-cim")).toBeDisabled();

    fireEvent.change(name, { target: { value: "web-01-e2e" } });
    expect(screen.getByTestId("save-cim")).toBeEnabled();
    fireEvent.click(screen.getByTestId("save-cim"));

    await waitFor(() => expect(mocks.patchState).toHaveBeenCalledTimes(1));
    const [runId, values] = mocks.patchState.mock.calls[0] as [string, { sized_cim: Cim }];
    expect(runId).toBe(RUN);
    expect(values.sized_cim.compute_units[0].name).toBe("web-01-e2e");
    expect(values.sized_cim.compute_units[1].name).toBe("db-01");
    expect(values.sized_cim.clusters).toHaveLength(2);
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "success" }));
    const title = (mocks.toast.mock.calls[0][0] as { title: React.ReactElement<{ children: string }> }).title;
    expect(title.props.children).toBe(CIM_SAVED_MESSAGE);
  });

  it("is read-only outside review_cim and shows the hint", () => {
    renderWithProviders(<CimTab runId={RUN} cim={makeCim()} editable={false} readOnlyReason="Paused elsewhere." onSaved={() => undefined} />);
    expect(screen.getByTestId("cim-readonly")).toHaveTextContent("Paused elsewhere.");
    expect(screen.queryByTestId("save-cim")).toBeNull();
    expect(screen.getByTestId("unit-name-0").tagName).toBe("DIV");
    expect(screen.getByTestId("unit-name-0")).toHaveTextContent("web-01");
  });

  it("applies bulk image ref to the selected rows only", async () => {
    renderWithProviders(<CimTab runId={RUN} cim={makeCim()} editable onSaved={() => undefined} />);
    fireEvent.click(screen.getByTestId("cim-select-1"));
    expect(screen.getByTestId("cim-bulk-bar")).toHaveTextContent("1 selected");
    fireEvent.change(screen.getByTestId("bulk-image-input"), { target: { value: "ami-123" } });
    fireEvent.click(screen.getByTestId("bulk-set-image"));
    fireEvent.click(screen.getByTestId("save-cim"));
    await waitFor(() => expect(mocks.patchState).toHaveBeenCalledTimes(1));
    const [, values] = mocks.patchState.mock.calls[0] as [string, { sized_cim: Cim }];
    expect(values.sized_cim.compute_units[0].image_ref).toBeNull();
    expect(values.sized_cim.compute_units[1].image_ref).toBe("ami-123");
  });

  it("filters rows with the global search", () => {
    renderWithProviders(<CimTab runId={RUN} cim={makeCim()} editable={false} onSaved={() => undefined} />);
    expect(screen.getAllByTestId("cim-row")).toHaveLength(2);
    fireEvent.change(screen.getByTestId("cim-filter"), { target: { value: "db-0" } });
    expect(screen.getAllByTestId("cim-row")).toHaveLength(1);
    expect(screen.getByTestId("unit-name-1")).toHaveTextContent("db-01");
  });

  it("refuses invalid raw JSON on save and sends valid JSON", async () => {
    renderWithProviders(<CimTab runId={RUN} cim={makeCim()} editable onSaved={() => undefined} />);
    fireEvent.click(screen.getByTestId("cim-raw-toggle"));
    const textarea = screen.getByTestId("cim-json") as HTMLTextAreaElement;
    expect(JSON.parse(textarea.value).compute_units).toHaveLength(2);

    fireEvent.change(textarea, { target: { value: "{ not json" } });
    fireEvent.click(screen.getByTestId("save-cim"));
    expect(await screen.findByTestId("cim-error")).toHaveTextContent("not valid");
    expect(mocks.patchState).not.toHaveBeenCalled();

    const edited = makeCim();
    edited.compute_units[0].vcpus = 16;
    fireEvent.change(textarea, { target: { value: JSON.stringify(edited, null, 2) } });
    fireEvent.click(screen.getByTestId("save-cim"));
    await waitFor(() => expect(mocks.patchState).toHaveBeenCalledTimes(1));
    const [, values] = mocks.patchState.mock.calls[0] as [string, { sized_cim: Cim }];
    expect(values.sized_cim.compute_units[0].vcpus).toBe(16);
  });

  it("validateCim rejects payloads without compute units", () => {
    expect(() => validateCim({})).toThrow(/compute_units/);
    expect(() => validateCim({ compute_units: [{ id: "", name: "x" }] })).toThrow(/id/);
    expect(validateCim(makeCim()).compute_units).toHaveLength(2);
  });
});
