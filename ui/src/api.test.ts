import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, onUnauthorized } from "./api";

function mockFetch(status: number, body: unknown, contentType = "application/json") {
  const fetchMock = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "status",
    headers: { get: () => contentType },
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("posts run creation with the full body", async () => {
    const fetchMock = mockFetch(201, { run_id: "r1" });
    const options = { cloud: "aws", environment: "dev", owner: "o", skip_validation: true, skip_opa: false, no_mcp: true, dry_run: false, llm_review_notes: true, pause_points: ["review_cim"] };
    const record = await api.createRun({ discovery: { x: 1 }, options, input_filename: "d.json", start: true, name: "first", tags: ["a"], connection_id: null });
    expect(record.run_id).toBe("r1");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/runs");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(JSON.parse(init.body as string)).toMatchObject({ discovery: { x: 1 }, input_filename: "d.json", start: true, name: "first", tags: ["a"] });
  });

  it("turns error responses into ApiError with the detail message", async () => {
    mockFetch(400, { detail: "cloud must be one of aws, azure" }, "text/plain");
    await expect(api.getRun("nope")).rejects.toMatchObject({ status: 400, message: "cloud must be one of aws, azure" } satisfies Partial<ApiError>);
  });

  it("notifies listeners on 401", async () => {
    mockFetch(401, "authentication required", "text/plain");
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledWith(401);
    off();
  });

  it("encodes artifact paths segment by segment", async () => {
    const fetchMock = mockFetch(200, "resource {}", "text/plain");
    const text = await api.artifact("r1", "aws-migration/compute web.tf");
    expect(text).toBe("resource {}");
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe("/api/runs/r1/artifacts/aws-migration/compute%20web.tf");
  });
});
