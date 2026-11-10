# hopshift docs

Implementation-accurate documentation for the current codebase.

Last refreshed: 2026-11-10

## At a glance

- Purpose: migrate infrastructure from any source to any target through one canonical model.
  A discovery payload is translated into the Canonical Infrastructure Model (CIM), rendered as
  Terraform for the chosen target, validated, checked against compliance controls, reviewed by
  people and deployed through stored connections.
- Sources and targets are plugins. Built in today: the VMware vSphere source
  (`vmware-discovery-stage1`) and the AWS, Azure, GCP and OpenStack targets. Both registries are
  listed by `GET /api/meta`.
- Runtime shape: a deterministic LangGraph pipeline with optional model use at the edges
  (review notes, and the `llm`/`hybrid` generation modes).
- Core contract: the CIM is the boundary. Nothing downstream of it knows a source field name;
  nothing upstream of it knows a target resource type.

The pipeline runs `ingest`, `blocker_parser`, `enricher`, `cim_mapper`, `sizer`, `mcp_client`,
`hcl_generator`, `validator` and `reporter`, in that order. The reporter always runs; Terraform
files are written only when validation passed. The diagrams live in
[architecture.md](architecture.md).

## Docs map

Start here:

- [architecture.md](architecture.md): sources, the CIM, targets, the two registries, the pipeline, platform services, API, UI, storage layout, threat model.
- [setup.md](setup.md): Docker and local setup, configuration, first administrator, production checklist, operations.

Extending:

- [plugins.md](plugins.md): how to write and register a source or a target package.
- [support-matrix.md](support-matrix.md): tiers (`tested`, `validated`, `experimental`), what each guarantees, evidence per source and target.
- Sources: [sources/vmware.md](sources/vmware.md).
- Targets: [targets/aws.md](targets/aws.md), [targets/azure.md](targets/azure.md), [targets/gcp.md](targets/gcp.md), [targets/openstack.md](targets/openstack.md), [targets/proxmox.md](targets/proxmox.md) (in progress).

Platform:

- [security.md](security.md): accounts, MFA, single sign-on, API tokens, headers, retention, evidence for SOC 2 / HIPAA / CIS.
- [compliance.md](compliance.md): compliance-as-code on the generated Terraform: control matrix and report format.
- [connections.md](connections.md): target connections: providers, sign-in methods, fields, Terraform environment mapping.
- [deployments.md](deployments.md): Terraform plan / apply / destroy with approval gates, state, LocalStack recipe.
- [api.md](api.md): the HTTP API, endpoint by endpoint, with roles.
- [ui.md](ui.md): the web UI: pages, shortcuts, building and testing.
- [ci.md](ci.md): continuous integration, bots, release pipeline, and how to run the same checks locally.

Core:

- [pipeline.md](pipeline.md): graph order, node responsibilities, retries, `MigrationState`.
- [cli.md](cli.md): commands, options, and practical examples.
- [configuration.md](configuration.md): runtime config contract, environment overrides and CLI override behaviour.
- [cim-and-translation.md](cim-and-translation.md): CIM models, the source registry and the VMware translation rules.
- [output-and-validation.md](output-and-validation.md): output layout, quarantine and report artifacts, validation gates, policies.
- [discovery-schema.md](discovery-schema.md): the VMware discovery JSON contract, gaps in the current output, and the proposed 1.1.0 fields.
- [ai-usage.md](ai-usage.md): where a model is used today, where it is planned, and what is deliberately rule-based.
- [runtime-and-api.md](runtime-and-api.md): the run service layer (pause points, state patching, re-run, events).

History:

- [platform-plan.md](platform-plan.md): the phase 3 build contract (kept for reference, not maintained).

## Command line overview

Primary command: `hopshift` (also `python -m hopshift.cli.main`).

Core commands:

- `terragen`: run the full pipeline from a discovery JSON to Terraform output (deterministic by default; `--mode llm|hybrid` for model-written generation).
- `assess`: deterministic per-resource risk assessment of the whole inventory, written as JSON and Markdown.
- `serve`: start the platform (API, Swagger UI and the built web UI).
- `report`: read generated artifacts from an existing output directory.
- `mcp-check`: validate Terraform MCP connectivity before an `llm`/`hybrid` run.
- `admin`, `secrets`, `audit`, `runs`: platform administration from the shell.

Quick-start examples:

```bash
# Full pipeline run
hopshift terragen --input discovery.json --cloud aws --environment prod --owner platform-team

# Read the output summary from the output directory
hopshift report output --format text

# Check Terraform MCP connectivity (llm/hybrid modes only)
hopshift mcp-check --servers terraform --timeout 10 --format text
```

Most-used `terragen` flags:

- Required: `--input`, `--cloud` (a registered target name), `--environment`, `--owner`
- Useful optional: `--mode`, `--llm-provider`, `--llm-model`, `--output-dir`, `--config`
- Control flags: `--dry-run`, `--skip-validation`, `--skip-opa`, `--no-mcp`

For complete option details, see [cli.md](cli.md).

## Important architecture notes

- Targets and sources are resolved through `hopshift/targets/registry.py` and
  `hopshift/sources/registry.py`. The CLI `--cloud` choices, the API `cloud` option, the sizer,
  the deterministic renderer and the validator all read the target registry.
- The active graph uses `mcp_client`, not `rag_retriever` (which exists in source but is not wired).
- Validation happens in two phases: the generation feedback loop inside `hcl_generator`
  (`llm`/`hybrid` modes) and the final deterministic gate in `validator`.
- `reporter` runs after `validator` on every path; unvalidated Terraform is never written to output.
- MCP retrieval can be disabled with `mcp.enabled: false` or `terragen --no-mcp`; it is only used by the `llm`/`hybrid` modes.

## Canonical terms

Use these terms consistently in code, docs, and review notes:

- CIM
- source, target (not "hypervisor" and "cloud" when the generic thing is meant)
- SourceSpec, TargetSpec
- ComputeUnit
- StorageVolume
- NetworkTopology
- ClusterSemantics
- MigrationState
- blocker
- quarantine queue
- sizing lookup
- HCL
