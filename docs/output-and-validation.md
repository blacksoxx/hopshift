# Output And Validation

This document covers generated file layout and deterministic validation behavior.

## Output Layout

Generated files are written under output.base_dir by reporter.

Path root is provider-specific:

- aws-migration/
- azure-migration/
- gcp-migration/
- openstack-migration/

Typical folders under each provider root:

- networking/
- compute/
- storage/
- placement/

Common artifact files in base_dir:

- quarantine_report.json
- review_notes.md

Notes:

- reporter writes only relative paths from hcl_output.
- reporter rejects unsafe paths (absolute paths or path traversal).
- when output.overwrite is true, provider root directories are deleted before writing fresh HCL.

## AWS Module Synthesis

hcl_generator contains AWS-specific synthesis that can add module layout files:

- aws-migration/providers.tf
- aws-migration/locals.tf
- aws-migration/main.tf
- aws-migration/modules/networking/*
- aws-migration/modules/compute/*
- aws-migration/modules/storage/*
- aws-migration/modules/placement/*

This synthesis normalizes generated output into a runnable root+modules structure.

## Validation Stages

Validation is executed in two phases.

Phase 1: hcl_generator internal loop

- Parses and validates LLM JSON response.
- Enforces output path policy and .tf-only file suffix.
- Enforces security guardrails: public exposure patterns, code-execution constructs (provisioner blocks, external/http data sources, null_resource, local_file), and `source = ...` assignments that are not local `./` modules or providers on the per-cloud allow-list.
- Rejects output paths that are absolute or contain `..`.
- Runs terraform validate/tflint/OPA through deterministic helpers.
- Feeds errors/warnings back into subsequent generation attempts.

Phase 2: validator final gate

- Re-runs terraform init/validate and tflint through validation.tf_runner, inside the provider root directory (running in the workspace root would validate an empty module), then OPA, according to config flags.
- Produces final validation_result.
- On failure, appends validator-stage quarantine entries and sets status failed.
- The reporter always runs next. On failure it writes quarantine_report.json and review_notes.md but no HCL files, and the CLI exits 1.

## Validation Flags

- --skip-validation disables terraform validate, tflint, and OPA.
- --skip-opa disables only OPA.

Both flags mutate runtime config before pipeline execution.

## Quarantine Report

Quarantine entries are written as JSON objects with:

- compute_unit_id
- compute_unit_name
- reasons
- stage

stage values:

- blocker_parser
- validator
