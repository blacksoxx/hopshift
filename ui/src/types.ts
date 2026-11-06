export type RunStatus = "created" | "running" | "paused" | "succeeded" | "failed" | "error";

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
  pause_points: string[];
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
  executing?: boolean;
}

export interface RunEvent {
  ts: string;
  type: "start" | "node" | "paused" | "patch" | "resume" | "rerun" | "error" | "end";
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

export interface RunState {
  run_id: string;
  status: RunStatus;
  next: string[];
  values: {
    sized_cim?: Cim;
    cim?: Cim;
    quarantine_queue?: QuarantineItem[];
    validation_result?: ValidationResult;
    hcl_output?: Record<string, string>;
    messages?: string[];
    status?: string;
    [key: string]: unknown;
  };
}

export interface Meta {
  clouds: string[];
  modes: string[];
  pause_points: Record<string, string>;
  nodes: string[];
  default_pause_points: string[];
}

export interface Artifact {
  path: string;
  size: number;
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
