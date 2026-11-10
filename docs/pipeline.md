# Pipeline And State

This document describes the active LangGraph workflow and state contract as implemented.

## Graph Execution Order

Defined in hopshift/pipeline/graph.py:

1. ingest
2. blocker_parser
3. enricher
4. cim_mapper
5. sizer
6. mcp_client
7. hcl_generator
8. validator
9. reporter

Edges:

- START -> ingest
- ingest -> blocker_parser -> enricher -> cim_mapper -> sizer -> mcp_client -> hcl_generator -> validator
- validator -> reporter (always)
- reporter -> END

## Node Responsibilities

- ingest: Validates and normalizes initial discovery input and runtime config in state.
- blocker_parser: Detects hard blockers, removes blocked ComputeUnits from active workload, appends quarantine items.
- enricher: Applies deterministic metadata enrichment before translation.
- cim_mapper: Builds CIM document from discovery payload.
- sizer: Applies the target's sizing table (resolved through the target registry) to each ComputeUnit.
- mcp_client: Pulls Terraform provider documentation snippets from Terraform MCP server and stores mcp_context.
- hcl_generator: Renders Terraform with the target package's renderers (`generation.mode: deterministic`, the default). In `llm`/`hybrid` modes the model proposes files inside a validation feedback loop; either way the output goes through the same validator gate.
- validator: Runs the final deterministic gate via hopshift.validation.tf_runner (terraform init/validate and tflint inside the target root, e.g. aws-migration/; tflint is skipped for targets whose registry entry has no ruleset unless validation.run_tflint_<target> is true) plus OPA (gate and compliance policies), and sets validation_result, compliance_result and status.
- reporter: Always runs. Writes quarantine_report.json and review_notes.md; writes HCL files only when validation_result.passed is true; writes nothing when output.dry_run is true. Sets the final status to succeeded or failed.

## Retry Behavior

There is no graph-level retry edge back to hcl_generator.

Retries happen inside hcl_generator:

- max_retries resolved from validation.max_retries, fallback pipeline.max_retries, fallback default 3.
- Each attempt rebuilds prompt with validation feedback from previous attempt.
- On exhausted retries, hcl_generator returns last candidate and validation_result; final pass/fail is still decided by validator.

## MigrationState Contract

Defined in hopshift/pipeline/state.py:

Required top-level fields:

- discovery_data: the discovery payload.
- config: runtime config map.
- target_provider: the target name (lower-case registry name; `TargetProvider` normalises the string, it is not an enum).
- cim: CanonicalInfrastructureModel.
- sized_cim: CanonicalInfrastructureModel after sizing lookup.
- mcp_context: Terraform docs context from MCP.
- hcl_output: map of output path -> HCL content.
- validation_result: pass/fail flags plus errors and warnings.
- compliance_result: the compliance report built by hopshift.services.compliance.report (controls, statuses, framework counts).
- assessment_result: output of the assess graph (risk per resource).
- review_notes: generated report markdown.
- quarantine_queue: list of QuarantineItem.
- messages: audit trail strings.
- retry_count: integer generation retry count.
- status: pending | running | succeeded | failed.

QuarantineItem fields:

- compute_unit_id
- compute_unit_name
- reasons: list[str]
- stage: blocker_parser | validator

ValidationResult fields:

- passed
- terraform_validate_passed
- tflint_passed
- opa_passed
- errors
- warnings

## Exit Status

`hopshift terragen` exits 0 only when the final status is succeeded. On failure it prints the first validation errors to stderr and exits 1.

## Important Drift Note

A rag_retriever node exists in source, but the active graph uses mcp_client.
