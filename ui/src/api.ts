import type { Artifact, AssessmentResult, Meta, RunEvent, RunOptions, RunRecord, RunState } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

export const api = {
  health: () => request<{ ok: boolean; runs_dir: string }>("/health"),
  meta: () => request<Meta>("/meta"),
  config: () => request<Record<string, unknown>>("/config"),
  listRuns: () => request<RunRecord[]>("/runs"),
  createRun: (discovery: unknown, options: RunOptions, inputFilename: string, start = true) =>
    request<RunRecord>("/runs", {
      method: "POST",
      body: JSON.stringify({ discovery, options, input_filename: inputFilename, start }),
    }),
  getRun: (id: string) => request<RunRecord>(`/runs/${encodeURIComponent(id)}`),
  start: (id: string) => request<{ status: string }>(`/runs/${encodeURIComponent(id)}/start`, { method: "POST" }),
  resume: (id: string) => request<{ status: string }>(`/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  rerun: (id: string, node: string) =>
    request<{ status: string }>(`/runs/${encodeURIComponent(id)}/rerun`, { method: "POST", body: JSON.stringify({ node }) }),
  getState: (id: string) => request<RunState>(`/runs/${encodeURIComponent(id)}/state`),
  patchState: (id: string, values: Record<string, unknown>) =>
    request<RunRecord>(`/runs/${encodeURIComponent(id)}/state`, { method: "PATCH", body: JSON.stringify({ values }) }),
  events: (id: string, since = 0) => request<RunEvent[]>(`/runs/${encodeURIComponent(id)}/events?since=${since}`),
  artifacts: (id: string) => request<Artifact[]>(`/runs/${encodeURIComponent(id)}/artifacts`),
  artifact: (id: string, path: string) =>
    request<string>(`/runs/${encodeURIComponent(id)}/artifacts/${path.split("/").map(encodeURIComponent).join("/")}`),
  assess: (discovery: unknown, cloud: string) =>
    request<AssessmentResult>("/assess", { method: "POST", body: JSON.stringify({ discovery, cloud }) }),
};

/** Subscribe to a run's server-sent events. Returns an unsubscribe function. */
export function subscribeEvents(
  id: string,
  since: number,
  onEvent: (event: RunEvent) => void,
  onDone: (status: string) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/runs/${encodeURIComponent(id)}/events/stream?since=${since}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as RunEvent);
  source.addEventListener("done", (message) => {
    const payload = JSON.parse((message as MessageEvent).data) as { status: string };
    source.close();
    onDone(payload.status);
  });
  source.onerror = () => {
    source.close();
    onDone("disconnected");
  };
  return () => source.close();
}

export const TERMINAL_STATUSES = new Set(["succeeded", "failed", "error"]);
