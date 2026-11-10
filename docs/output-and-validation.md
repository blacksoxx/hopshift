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

## OPA Policies

Policies live in hopshift/validation/policies and are evaluated with `opa eval` (binary mode) or an OPA server. They run in both validation phases.

Input shape: the generated files are parsed with python-hcl2 (validation/hcl_parser.py) and OPA receives a structured document, so rules check attributes per resource instead of matching substrings in file text:

- input.resources[]: file, type, name, address, config (attributes and nested blocks, literals unquoted, expressions kept as `${...}` strings)
- input.data_sources[], input.modules[], input.providers[], input.required_providers[], input.variables[], input.outputs[]
- input.parse_errors[]: files that are not valid HCL (any entry is a deny)
- input.generated_files: the raw path -> content map, kept for ad-hoc rules

Rules (all in package hopshift, `import rego.v1`, compatible with OPA 0.68 and 1.x):

- no_open_ingress: 0.0.0.0/0 or ::/0 ingress on AWS security groups and rules (both styles), Azure NSG rules (`*`, Internet, Any, 0.0.0.0/0), GCP firewalls with allow blocks, OpenStack security group rules.
- no_public_s3: public S3 ACLs, disabled public access blocks, bucket policies with Principal `*`, GCS allUsers/allAuthenticatedUsers, Azure anonymous containers and storage accounts that do not set allow_nested_items_to_be_public = false.
- encryption_at_rest: aws_ebs_volume and aws_instance block devices must set encrypted = true, Azure managed disks must not disable encryption, OpenStack volumes must set a volume_type.
- tags_required: every taggable resource must carry Environment, Owner, MigratedFrom (lowercase labels on GCP; Key=Value list entries on OpenStack networks). Metadata built from `merge(var.common_tags, ...)` or a locals map is accepted; anything else is denied.
- no_code_execution: provisioners, null_resource/local_file, external/http data sources, non-local module sources, and unparseable files.

The policies_dir setting is resolved relative to the working directory first and then to the repository root, so the CLI works from any directory.

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
