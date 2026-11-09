import type {
  ApiToken,
  Artifact,
  AssessmentResult,
  AuditEntry,
  AuthStatus,
  AuthUser,
  ComplianceReport,
  Connection,
  ConnectionCatalog,
  ConnectionTest,
  CreateRunRequest,
  Dashboard,
  Deployment,
  DeploymentAction,
  DeploymentLog,
  DeviceFlowStart,
  Meta,
  PostureCheck,
  Role,
  RunDiff,
  RunEvent,
  RunRecord,
  RunState,
  SettingsPayload,
  TerraformStateSummary,
  TerraformVariable,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type Listener = (status: number) => void;
const unauthorizedListeners = new Set<Listener>();

/** Subscribe to 401 responses (the auth provider redirects to the login page). */
export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

async function request<T>(path: string, init?: RequestInit & { raw?: boolean }): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const text = await response.text();
    let body: unknown = text;
    let message = text || response.statusText;
    try {
      body = JSON.parse(text);
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string") message = detail;
    } catch {
      /* plain text error */
    }
    if (response.status === 401) unauthorizedListeners.forEach((listener) => listener(401));
    throw new ApiError(response.status, message, body);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.text()) as unknown as T;
}

const enc = encodeURIComponent;
const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  // meta
  health: () => request<{ ok: boolean; runs_dir: string; version: string }>("/health"),
  meta: () => request<Meta>("/meta"),
  config: () => request<Record<string, unknown>>("/config"),
  dashboard: () => request<Dashboard>("/dashboard"),

  // auth
  authStatus: () => request<AuthStatus>("/auth/status"),
  setup: (username: string, password: string, name: string) => request<AuthUser>("/auth/setup", json({ username, password, name })),
  login: (username: string, password: string, totp_code?: string) =>
    request<AuthUser>("/auth/login", json({ username, password, totp_code: totp_code || undefined })),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<AuthUser>("/auth/me"),
  changePassword: (current_password: string, new_password: string) => request<void>("/auth/password", json({ current_password, new_password })),
  mfaEnroll: () => request<{ secret: string; otpauth_uri: string }>("/auth/mfa/enroll", { method: "POST" }),
  mfaConfirm: (code: string) => request<{ recovery_codes: string[] }>("/auth/mfa/confirm", json({ code })),
  mfaDisable: (password: string, code: string) => request<void>("/auth/mfa/disable", json({ password, code })),
  oidcLoginUrl: () => `${API_BASE}/auth/oidc/login`,
  listTokens: (all = false) => request<ApiToken[]>(`/auth/tokens${all ? "?all=true" : ""}`),
  createToken: (name: string, role?: Role, expires_days?: number) => request<{ id: string; token: string }>("/auth/tokens", json({ name, role, expires_days })),
  deleteToken: (id: string) => request<void>(`/auth/tokens/${enc(id)}`, { method: "DELETE" }),

  // users (admin)
  listUsers: () => request<AuthUser[]>("/users"),
  createUser: (body: { username: string; password: string; name: string; role: Role }) => request<AuthUser>("/users", json(body)),
  updateUser: (id: string, body: Partial<{ name: string; role: Role; disabled: boolean; password: string }>) =>
    request<AuthUser>(`/users/${enc(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteUser: (id: string) => request<void>(`/users/${enc(id)}`, { method: "DELETE" }),
  resetUserMfa: (id: string) => request<void>(`/users/${enc(id)}/mfa/reset`, { method: "POST" }),

  // audit (admin)
  audit: (params: { limit?: number; offset?: number; action?: string; actor?: string; since?: string; target_id?: string; outcome?: string } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<{ entries: AuditEntry[]; total: number }>(`/audit?${query.toString()}`);
  },
  auditVerify: () => request<{ ok: boolean; entries: number; broken_at: number | null; message: string }>("/audit/verify"),
  auditExportUrl: () => `${API_BASE}/audit/export`,

  // settings
  settings: () => request<SettingsPayload>("/settings"),
  updateSettings: (values: Record<string, unknown>) => request<SettingsPayload>("/settings", { method: "PUT", body: JSON.stringify({ values }) }),
  posture: () => request<{ checks: PostureCheck[] }>("/settings/posture"),

  // runs
  listRuns: (params: { status?: string; cloud?: string; tag?: string; q?: string } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    const suffix = query.toString();
    return request<RunRecord[]>(`/runs${suffix ? `?${suffix}` : ""}`);
  },
  createRun: (body: CreateRunRequest) => request<RunRecord>("/runs", json(body)),
  getRun: (id: string) => request<RunRecord>(`/runs/${enc(id)}`),
  updateRun: (id: string, body: { name?: string | null; tags?: string[]; connection_id?: string | null; clear_connection?: boolean }) =>
    request<RunRecord>(`/runs/${enc(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteRun: (id: string) => request<void>(`/runs/${enc(id)}`, { method: "DELETE" }),
  start: (id: string) => request<{ status: string }>(`/runs/${enc(id)}/start`, { method: "POST" }),
  resume: (id: string) => request<{ status: string }>(`/runs/${enc(id)}/resume`, { method: "POST" }),
  cancel: (id: string) => request<{ status: string }>(`/runs/${enc(id)}/cancel`, { method: "POST" }),
  rerun: (id: string, node: string) => request<{ status: string }>(`/runs/${enc(id)}/rerun`, json({ node })),
  getState: (id: string) => request<RunState>(`/runs/${enc(id)}/state`),
  patchState: (id: string, values: Record<string, unknown>) =>
    request<RunRecord>(`/runs/${enc(id)}/state`, { method: "PATCH", body: JSON.stringify({ values }) }),
  events: (id: string, since = 0) => request<RunEvent[]>(`/runs/${enc(id)}/events?since=${since}`),
  artifacts: (id: string) => request<Artifact[]>(`/runs/${enc(id)}/artifacts`),
  artifact: (id: string, path: string) => request<string>(`/runs/${enc(id)}/artifacts/${path.split("/").map(enc).join("/")}`),
  artifactsArchiveUrl: (id: string) => `${API_BASE}/runs/${enc(id)}/artifacts/archive`,
  diff: (id: string, otherId: string) => request<RunDiff>(`/runs/${enc(id)}/diff/${enc(otherId)}`),
  compliance: (id: string) => request<ComplianceReport>(`/runs/${enc(id)}/compliance`),
  assess: (discovery: unknown, cloud: string) => request<AssessmentResult>("/assess", json({ discovery, cloud })),

  // connections
  connectionCatalog: () => request<ConnectionCatalog>("/connections/methods"),
  listConnections: () => request<Connection[]>("/connections"),
  getConnection: (id: string) => request<Connection>(`/connections/${enc(id)}`),
  createConnection: (body: { name: string; provider: string; auth_method: string; config: Record<string, unknown>; secret: Record<string, unknown> }) =>
    request<Connection>("/connections", json(body)),
  updateConnection: (id: string, body: { name?: string; config?: Record<string, unknown>; secret?: Record<string, unknown> }) =>
    request<Connection>(`/connections/${enc(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteConnection: (id: string) => request<void>(`/connections/${enc(id)}`, { method: "DELETE" }),
  testConnection: (id: string) => request<ConnectionTest>(`/connections/${enc(id)}/test`, { method: "POST" }),
  deviceStart: (id: string) => request<DeviceFlowStart>(`/connections/${enc(id)}/device/start`, { method: "POST" }),
  devicePoll: (id: string, flow_id: string) => request<{ status: string; message: string }>(`/connections/${enc(id)}/device/poll`, json({ flow_id })),

  // deployments
  listDeployments: (runId: string) => request<Deployment[]>(`/runs/${enc(runId)}/deployments`),
  createDeployment: (runId: string, body: { action: DeploymentAction; connection_id?: string | null; plan_id?: string | null; confirmation?: string }) =>
    request<Deployment>(`/runs/${enc(runId)}/deployments`, json(body)),
  getDeployment: (runId: string, id: string) => request<Deployment>(`/runs/${enc(runId)}/deployments/${enc(id)}`),
  deploymentLog: (runId: string, id: string, since = 0) => request<DeploymentLog>(`/runs/${enc(runId)}/deployments/${enc(id)}/log?since=${since}`),
  deploymentPlan: (runId: string, id: string) => request<Record<string, unknown>>(`/runs/${enc(runId)}/deployments/${enc(id)}/plan`),
  cancelDeployment: (runId: string, id: string) => request<Deployment>(`/runs/${enc(runId)}/deployments/${enc(id)}/cancel`, { method: "POST" }),
  deployVariables: (runId: string) => request<TerraformVariable[]>(`/runs/${enc(runId)}/deploy/variables`),
  setDeployVariables: (runId: string, values: Record<string, unknown>) =>
    request<TerraformVariable[]>(`/runs/${enc(runId)}/deploy/variables`, { method: "PUT", body: JSON.stringify({ values }) }),
  deployState: (runId: string) => request<TerraformStateSummary>(`/runs/${enc(runId)}/deploy/state`),
};

/** Subscribe to a run's server-sent events. Returns an unsubscribe function. */
export function subscribeEvents(
  id: string,
  since: number,
  onEvent: (event: RunEvent) => void,
  onDone: (status: string) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/runs/${enc(id)}/events/stream?since=${since}`, { withCredentials: true });
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

/** Subscribe to a deployment's log stream. Returns an unsubscribe function. */
export function subscribeDeploymentLog(
  runId: string,
  deploymentId: string,
  since: number,
  onLine: (line: string) => void,
  onDone: (status: string) => void,
): () => void {
  const source = new EventSource(`${API_BASE}/runs/${enc(runId)}/deployments/${enc(deploymentId)}/log/stream?since=${since}`, { withCredentials: true });
  source.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data) as { line?: string } | string;
      onLine(typeof payload === "string" ? payload : (payload.line ?? message.data));
    } catch {
      onLine(message.data);
    }
  };
  source.addEventListener("done", (message) => {
    let status = "done";
    try {
      status = (JSON.parse((message as MessageEvent).data) as { status?: string }).status ?? "done";
    } catch {
      /* ignore */
    }
    source.close();
    onDone(status);
  });
  source.onerror = () => {
    source.close();
    onDone("disconnected");
  };
  return () => source.close();
}

export const TERMINAL_STATUSES = new Set(["succeeded", "failed", "error", "cancelled"]);
