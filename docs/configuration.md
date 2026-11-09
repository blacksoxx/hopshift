# Configuration Reference

Runtime configuration is loaded from config.yaml and then selectively overridden by CLI flags.

## generation

- mode: deterministic | llm | hybrid (default deterministic)

Behavior:

- deterministic renders Terraform from the templates in providers/ (networking, compute, storage, placement, runtime). No LLM, no MCP, no API key. Output is a flat root module per provider and is identical for identical input.
- llm keeps the original LLM generation loop (requires llm.* and, when mcp.enabled, docker).
- hybrid renders deterministically first and only falls back to the LLM loop when the deterministic output fails validation; the deterministic errors are the first feedback round.
- Override per run with `terragen --mode` or the VMWARE_MIGRATION_AGENT_GENERATION_MODE environment variable.

## llm

- provider: anthropic | openai | google
- models: per-provider defaults
- temperature_hcl: must stay 0.0 (sent to openai/google only; Claude 5-family models reject sampling parameters)
- temperature_report: report generation temperature (same caveat)
- max_tokens (output budget per call, default 16000)
- timeout_seconds (default 300)
- effort: low | medium | high | xhigh | max (Anthropic reasoning depth; omit for the API default)
- sdk_max_retries, retry_attempts, retry_backoff_seconds: transient-error retries (rate limits, 5xx, network, timeouts) with jittered exponential backoff
- enable_fallbacks: Anthropic server-side refusal fallbacks (default true); a declined request is re-run on Anthropic's recommended fallback model inside the same call

Behavior of the llm/hybrid generation path:

- HCL is requested as schema-constrained JSON ({"files": [{"path", "content"}]}) via structured outputs, so parsing never depends on the model formatting text correctly.
- The prompt is split into a stable, cacheable prefix (requirements, full CIM, documentation) and a volatile part (batch scope, attempt, validation feedback) so retries and batches hit the prompt cache.
- Estates larger than pipeline.batch_size ComputeUnits are generated in batches: one call for main/networking/placement, then one call per batch for compute/storage, each told which resources already exist. A truncated response halves the batch size for the next attempt.
- Refusals and truncation become validation feedback for the next attempt instead of crashing the run; token usage per call and per run is recorded in the run messages.

Notes:

- hcl_generator uses LLMClient.generate_hcl.
- reporter uses LLMClient.generate_review_notes.

## target_cloud

Default target provider for generation unless overridden by CLI --cloud.

## pipeline

- batch_size
- max_retries
- abort_threshold_pct

Notes:

- hcl_generator resolves retry count from validation.max_retries first, then pipeline.max_retries.

## validation

- run_terraform_validate
- run_tflint
- run_opa
- terraform_bin
- tflint_bin
- opa_mode (binary|server)
- opa_bin
- opa_server_url
- policies_dir
- terraform_plugin_cache_dir (Terraform provider cache shared across validation runs; empty disables it)

Behavior:

- validator executes terraform init + terraform validate when enabled.
- validator executes tflint when enabled.
- validator executes OPA policy evaluation when enabled.

## mcp

- enabled
- tool_timeout_seconds
- terraform.image
- terraform.toolsets (must be registry)

Behavior:

- mcp.enabled=false makes mcp_client skip retrieval and lets hcl_generator run without documentation context. The terragen --no-mcp flag sets this per run.
- mcp_client expects registry-only toolset for Terraform MCP retrieval.
- terraform.image should be pinned by tag and digest (image:tag@sha256:...); the docker CLI and a reachable daemon are required when enabled.

## output

- base_dir
- structure (template reference)
- write_quarantine_report
- quarantine_report_filename
- write_review_notes
- review_notes_filename
- write_compliance_report, compliance_report_json_filename, compliance_report_markdown_filename
- llm_review_notes (write review notes with the model; runs created through the API/UI can override per run)
- overwrite
- dry_run

Behavior:

- reporter writes hcl_output keys under output.base_dir only when validation passed.
- reporter always writes the quarantine report and review notes, except when dry_run = true, in which case nothing is written.
- reporter removes generated .tf files under provider root directories when overwrite = true.

## vsphere

- drs_rule_mapping
- hard_blockers
- soft_blockers

Behavior:

- blocker_parser enforces hard blockers before CIM mapping.
- soft blockers typically produce needs_review behavior later in pipeline.

## required_tags

Default tags injected into generated resources:

- Environment
- Owner
- MigratedFrom
- MigrationTool
- SourceVCenter
- GeneratedAt

CLI overwrites Environment and Owner at runtime.

## runtime

Service layer used by the API, the UI and the platform.

- runs_dir: one folder per run (run.json, discovery.json, events.jsonl, artifacts/, deploy/)
- checkpoint_db: LangGraph checkpoint database (pause / resume / re-run); empty keeps checkpoints in memory
- platform_db: SQLite database for users, sessions, tokens, connections, deployments, the audit log and settings overrides
- default_pause_points: `review_cim` (before hcl_generator) and/or `approve_output` (before reporter) for runs created through the runtime; the CLI never pauses

## security

- auth.mode: `required` (default) or `disabled` (development only; every caller is an anonymous admin)
- auth.session_hours, auth.idle_minutes: absolute and idle session expiry
- auth.mfa: `optional` or `required` (users without a second factor may only use the account endpoints until enrolled)
- auth.lockout_threshold, auth.lockout_minutes: failed-login lockout per account
- auth.oidc: `enabled`, `issuer`, `client_id`, `client_secret_env` (name of the environment variable holding the client secret), `scopes`, `allowed_domains`, `default_role`, `admin_groups`, `groups_claim`
- secret_key_env: environment variable holding the Fernet key(s) that encrypt stored credentials (default `VMA_SECRET_KEY`; comma-separated keys, the first encrypts, all decrypt)
- headers.hsts, headers.content_security_policy (`default` or `off`)
- allowed_origins: extra origins allowed to call the API with a session cookie
- api_docs: serve Swagger UI at /docs
- retention.runs_days, retention.audit_days: delete runs and prune audit entries older than N days (0 keeps everything); applied by the hourly sweeper and `vma runs prune`
- encrypt_run_inputs: store discovery.json encrypted with the secret key

A few keys (`generation.mode`, the model settings, validation switches, default pause points, MFA policy, session lifetimes, lockout, retention, deploy gates) can be overridden from Settings in the UI by an administrator; the overrides live in `platform_db` and are applied over this file when a run is created.

## deploy

- terraform_bin
- timeout_minutes: maximum duration of a plan, apply or destroy
- allow_apply, allow_destroy: global gates; a request against a disabled action is refused and audited
- remote_state.enabled, remote_state.type (`s3` | `azurerm` | `gcs`), remote_state.config: rendered into `backend_override.tf` in the deployment workspace; by default state stays local under the run's `deploy/state/` folder

## logging

- level
- format (json or console)
- detailed_log_file, detailed_log_level: optional second sink (kept under output/ so the container can run with a read-only root filesystem)
