export type RunStatus = "created" | "running" | "paused" | "succeeded" | "failed" | "error" | "cancelled";
export type Role = "viewer" | "operator" | "admin";

export interface RunOptions {
  cloud: string;
  environment: string;
  owner: string;
  mode?: string | null;
  llm_provider?: string | null;
  llm_model?: string | null;
  llm_base_url?: string | null;
  skip_validation: boolean;
  skip_opa: boolean;
  no_mcp: boolean;
  dry_run: boolean;
  llm_review_notes: boolean;
  pause_points: string[] | null;
}

export interface RunRecord {
  run_id: string;
  created_at: string;
  updated_at: string;
  status: RunStatus;
  cloud: string;
  mode: string;
  options: RunOptions;
  input_filename: string;
  run_dir: string;
  paused_before: string | null;
  pause_point: string | null;
  error: string | null;
  event_count: number;
  name?: string | null;
  tags?: string[];
  connection_id?: string | null;
  created_by?: string | null;
  cancel_requested?: boolean;
  executing?: boolean;
}

export interface CreateRunRequest {
  discovery: unknown;
  options: RunOptions;
  input_filename: string;
  start: boolean;
  name?: string | null;
  tags?: string[];
  connection_id?: string | null;
}

export interface RunEvent {
  ts: string;
  type: "start" | "node" | "paused" | "patch" | "resume" | "rerun" | "error" | "end" | "cancelled";
  node: string | null;
  summary: Record<string, unknown>;
  messages: string[];
}

export interface ComputeUnit {
  id: string;
  name: string;
  vcpus: number;
  ram_mb: number;
  migration_status: string;
  blockers: string[];
  cluster_ref: string | null;
  guest_os?: string | null;
  power_state?: string | null;
  architecture?: string;
  image_ref?: string | null;
  has_vtpm?: boolean;
  nics: { name: string; port_group_ref: string }[];
  storage_volumes: { id: string; size_gb: number; datastore: string | null }[];
  [key: string]: unknown;
}

export interface Cim {
  source_vcenter: string;
  source: { platform: string; name: string; hostname: string | null };
  target_provider: string;
  network_topology: { distributed_switches: { name: string; port_groups: { name: string; vlan_id: string }[] }[] };
  clusters: { name: string; semantics: string }[];
  compute_units: ComputeUnit[];
  [key: string]: unknown;
}

export interface QuarantineItem {
  compute_unit_id: string;
  compute_unit_name: string;
  reasons: string[];
  stage: string;
}

export interface ValidationResult {
  passed?: boolean;
  terraform_validate_passed?: boolean;
  tflint_passed?: boolean;
  opa_passed?: boolean;
  errors?: string[];
  warnings?: string[];
}

export interface ComplianceControl {
  id: string;
  title: string;
  level: "enforce" | "advisory";
  status: "pass" | "fail" | "advisory" | "not_applicable";
  frameworks: { cis?: string[]; soc2?: string[]; hipaa?: string[] };
  resources: string[];
  messages: string[];
  remediation?: string;
  description?: string;
}

export interface ComplianceReport {
  generated_at: string;
  cloud: string;
  summary: { controls: number; passed: number; failed: number; advisory: number; not_applicable: number };
  controls: ComplianceControl[];
  frameworks?: Record<string, Record<string, number>>;
}

export interface RunState {
  run_id: string;
  status: RunStatus;
  next: string[];
  values: {
    sized_cim?: Cim;
    cim?: Cim;
    quarantine_queue?: QuarantineItem[];
    validation_result?: ValidationResult;
    compliance_result?: ComplianceReport;
    hcl_output?: Record<string, string>;
    review_notes?: string;
    messages?: string[];
    status?: string;
    [key: string]: unknown;
  };
}

export interface Meta {
  version: string;
  clouds: string[];
  modes: string[];
  pause_points: Record<string, string>;
  nodes: string[];
  default_pause_points: string[];
  auth_mode: "required" | "disabled";
  features: { connections: boolean; deployments: boolean; secrets: boolean };
}

export interface Artifact {
  path: string;
  size: number;
}

export interface DiffFile {
  path: string;
  status: "added" | "removed" | "modified" | "same";
  diff: string;
}

export interface RunDiff {
  run_id: string;
  other_id: string;
  files: DiffFile[];
  summary: Record<string, number>;
}

export interface AssessmentResource {
  resource_type: string;
  resource_id: string;
  resource_name: string;
  risk_level: "safe" | "caution" | "elevated" | "critical";
  risk_score: number;
  safe_to_migrate: boolean;
  reasons: string[];
  missing_data: string[];
  recommendations: string[];
}

export interface AssessmentResult {
  generated_at: string;
  source_vcenter: string;
  target_provider: string;
  summary: { total_resources: number; safe: number; caution: number; elevated: number; critical: number };
  resources: AssessmentResource[];
}

export interface Dashboard {
  total: number;
  by_status: Record<string, number>;
  by_cloud: Record<string, number>;
  success_rate: number | null;
  series: { date: string; succeeded: number; failed: number; other: number }[];
  recent: RunRecord[];
  attention: RunRecord[];
}

// ── auth ──────────────────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  username: string;
  name: string | null;
  role: Role;
  auth_kind: "local" | "oidc" | string;
  mfa_enabled: boolean;
  mfa_enrollment_required?: boolean;
  created_at?: string;
  last_login_at?: string | null;
  disabled?: boolean;
}

export interface AuthStatus {
  setup_required: boolean;
  auth_mode: "required" | "disabled";
  oidc_enabled: boolean;
  mfa_policy: "optional" | "required";
  user?: AuthUser | null;
}

export interface ApiToken {
  id: string;
  name: string;
  role: Role;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  user_id?: string;
  username?: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  actor_kind: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  ip: string | null;
  user_agent: string | null;
  details: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface PostureCheck {
  id: string;
  title: string;
  status: "pass" | "warn" | "fail";
  detail: string;
  frameworks: string[];
}

export interface SettingSpec {
  key: string;
  type: "string" | "integer" | "boolean" | "choice" | "list";
  label: string;
  help: string;
  group: string;
  options: string[];
  minimum: number | null;
  maximum: number | null;
}

export interface SettingsPayload {
  effective: Record<string, unknown>;
  overrides: Record<string, unknown>;
  schema: SettingSpec[];
}

// ── connections ───────────────────────────────────────────────────────────────

export interface ConnectionField {
  key: string;
  label: string;
  type: "text" | "password" | "textarea" | "select" | "boolean" | "number";
  required: boolean;
  secret: boolean;
  help?: string;
  options?: string[];
  placeholder?: string;
  default?: string | boolean | number | null;
}

export interface ConnectionMethod {
  key: string;
  label: string;
  description: string;
  terraform_ready: boolean;
  fields: ConnectionField[];
}

export type ConnectionCatalog = Record<string, { label: string; methods: ConnectionMethod[] }>;

export interface Connection {
  id: string;
  name: string;
  provider: string;
  auth_method: string;
  config: Record<string, unknown>;
  status: "unverified" | "ok" | "failed";
  last_checked_at: string | null;
  last_check: { identity?: Record<string, unknown>; message?: string } | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  has_secret: boolean;
  secret_fields: string[];
  terraform_ready: boolean;
}

export interface ConnectionTest {
  ok: boolean;
  identity: Record<string, unknown>;
  message: string;
  checked_at: string;
}

export interface DeviceFlowStart {
  flow_id: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete?: string;
  expires_in: number;
  interval: number;
}

// ── deployments ───────────────────────────────────────────────────────────────

export type DeploymentAction = "plan" | "apply" | "destroy";
export type DeploymentStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Deployment {
  id: string;
  run_id: string;
  action: DeploymentAction;
  status: DeploymentStatus;
  connection_id: string | null;
  connection_name: string | null;
  provider: string | null;
  requested_by: string | null;
  approved_by: string | null;
  plan_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  summary: { add: number; change: number; destroy: number; replace?: number; resources: { address: string; type: string; actions: string[] }[] } | null;
  error: string | null;
}

export interface DeploymentLog {
  lines: string[];
  next: number;
  done: boolean;
}

export interface TerraformVariable {
  name: string;
  type: string;
  description: string;
  default: unknown;
  sensitive: boolean;
  required: boolean;
  value?: unknown;
}

export interface TerraformStateSummary {
  exists: boolean;
  resources?: { address: string; type: string }[];
  serial?: number;
  terraform_version?: string;
}
