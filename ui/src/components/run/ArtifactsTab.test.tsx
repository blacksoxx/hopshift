import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { ArtifactsTab, buildTree } from "./ArtifactsTab";
import { makeRun, renderWithProviders } from "./test-helpers";
import type { Artifact } from "@/types";

const mocks = vi.hoisted(() => ({
  artifacts: vi.fn(),
  artifact: vi.fn(),
  listRuns: vi.fn(),
  diff: vi.fn(),
}));

vi.mock("@/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api")>();
  return { ...actual, api: { ...actual.api, artifacts: mocks.artifacts, artifact: mocks.artifact, listRuns: mocks.listRuns, diff: mocks.diff } };
});

vi.mock("shiki", () => ({
  createJavaScriptRegexEngine: () => ({}),
  createHighlighter: async () => ({
    codeToHtml: (code: string) => `<pre class="shiki"><code>${code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre>`,
  }),
}));

const FILES: Artifact[] = [
  { path: "aws-migration/main.tf", size: 120 },
  { path: "aws-migration/compute_web-01-e2e.tf", size: 340 },
  { path: "aws-migration/variables.tf", size: 80 },
  { path: "quarantine_report.json", size: 55 },
];

const CONTENT: Record<string, string> = {
  "aws-migration/main.tf": 'module "x" {}',
  "aws-migration/compute_web-01-e2e.tf": 'resource "aws_instance" "web_01_e2e" {\n  ami = var.default_ami_id\n}',
  "aws-migration/variables.tf": 'variable "aws_region" {}',
  "quarantine_report.json": "[]",
};

const RUN = makeRun({ status: "succeeded", paused_before: null, pause_point: null });

describe("buildTree", () => {
  it("groups files by directory with directories first", () => {
    const tree = buildTree(FILES);
    expect(tree.map((node) => node.name)).toEqual(["aws-migration", "quarantine_report.json"]);
    expect(tree[0].children.map((node) => node.name)).toEqual(["compute_web-01-e2e.tf", "main.tf", "variables.tf"]);
    expect(tree[1].file?.size).toBe(55);
  });
});

describe("ArtifactsTab", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((fn) => fn.mockReset());
    mocks.artifacts.mockResolvedValue(FILES);
    mocks.artifact.mockImplementation(async (_run: string, path: string) => CONTENT[path] ?? "");
    mocks.listRuns.mockResolvedValue([]);
  });

  it("shows the empty state when nothing was written", async () => {
    mocks.artifacts.mockResolvedValue([]);
    renderWithProviders(<ArtifactsTab run={makeRun()} />);
    expect(await screen.findByText("No artifacts yet")).toBeInTheDocument();
  });

  it("lists files in a tree, preselects main.tf and shows the selected file's text", async () => {
    renderWithProviders(<ArtifactsTab run={RUN} />);
    const items = await screen.findAllByTestId("artifact-item");
    expect(items).toHaveLength(4);
    await waitFor(() => expect(screen.getByTestId("artifact-content")).toHaveTextContent('module "x" {}'));
    expect(screen.getByTestId("artifact-path")).toHaveTextContent("aws-migration/main.tf");

    const edited = items.find((item) => item.textContent?.includes("compute_web-01-e2e.tf"));
    expect(edited).toBeDefined();
    fireEvent.click(edited as HTMLElement);
    await waitFor(() => expect(screen.getByTestId("artifact-content")).toHaveTextContent('resource "aws_instance" "web_01_e2e"'));
    expect(screen.getByTestId("artifact-path")).toHaveTextContent("compute_web-01-e2e.tf");
    await waitFor(() => expect(screen.getByTestId("artifact-content")).toHaveAttribute("data-highlighted", "true"));
    expect(screen.getByTestId("artifact-content")).toHaveTextContent('resource "aws_instance" "web_01_e2e"');
  });

  it("collapses a directory", async () => {
    renderWithProviders(<ArtifactsTab run={RUN} />);
    await screen.findAllByTestId("artifact-item");
    fireEvent.click(screen.getByTestId("artifact-dir"));
    expect(screen.getAllByTestId("artifact-item")).toHaveLength(1);
  });

  it("renders a diff against another run", async () => {
    mocks.listRuns.mockResolvedValue([makeRun({ run_id: "20261108T100000Z-00000001", status: "succeeded", name: "Earlier" }), RUN]);
    mocks.diff.mockResolvedValue({
      run_id: RUN.run_id,
      other_id: "20261108T100000Z-00000001",
      summary: { modified: 1, same: 1 },
      files: [
        { path: "aws-migration/main.tf", status: "same", diff: "" },
        { path: "aws-migration/compute_web-01-e2e.tf", status: "modified", diff: "--- a\n+++ b\n@@ -1,2 +1,2 @@\n-  ami = old\n+  ami = var.default_ami_id\n   x = 1\n" },
      ],
    });
    renderWithProviders(<ArtifactsTab run={RUN} />);
    await screen.findAllByTestId("artifact-item");
    expect(screen.getByTestId("compare-select")).toBeEnabled();
  });
});
