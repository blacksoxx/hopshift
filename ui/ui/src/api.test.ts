import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

function mockFetch(status: number, body: unknown, contentType = "application/json") {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "status",
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? contentType : null) },
    json: async () => JSON.parse(text),
    text: async () => text,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("posts run creation with the expected body and returns the record", async () => {
    const fetchMock = mockFetch(201, { run_id: "r1", status: "created" });
    vi.stubGlobal("fetch", fetchMock);

    const record = await api.createRun({ virtual_machines: [] }, { cloud: "aws", environment: "dev", owner: "o", skip_validation: true, skip_opa: false, no_mcp: true, dry_run: false, pause_points: ["review_cim"] }, "lab.json", true);

    expect(record.run_id).toBe("r1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toMatchObject({ input_filename: "lab.json", start: true, options: { cloud: "aws", pause_points: ["review_cim"] } });
  });

  it("surfaces server error text with the status code", async () => {
    vi.stubGlobal("fetch", mockFetch(400, "Discovery JSON must include a 'virtual_machines' list", "text/plain"));

    await expect(api.getRun("x")).rejects.toMatchObject({ status: 400, message: expect.stringContaining("virtual_machines") } satisfies Partial<ApiError>);
  });

  it("returns artifact content as text", async () => {
    vi.stubGlobal("fetch", mockFetch(200, 'resource "aws_vpc" "x" {}', "text/plain; charset=utf-8"));

    const content = await api.artifact("r1", "aws-migration/networking_vpc.tf");

    expect(content).toContain("aws_vpc");
  });
});
