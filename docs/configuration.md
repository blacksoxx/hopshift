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

## logging

- level
- format (json or console)
