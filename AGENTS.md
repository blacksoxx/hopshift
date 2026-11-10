# AGENTS.md: project context for AI coding assistants

This file is read by Claude Code, Cursor, Copilot, and any other AI coding tool
working in this repository. It is the authoritative source of project intent,
constraints, and design decisions.

## Project purpose
hopshift migrates infrastructure from any source to any target through one canonical model.
A discovery payload (today: VMware vSphere, produced by an Ansible collection) is translated
into the Canonical Infrastructure Model (CIM), rendered as deployable, compliant Terraform for
a target (today: AWS, Azure, GCP, OpenStack), reviewed and approved by people, and deployed
through stored connections. Ships as a CLI (`hopshift`), an HTTP API and a web UI; runs in CI
or as a container (`ghcr.io/blacksoxx/hopshift`).

## Core constraint
This is a data transformation pipeline, not a chatbot. Default HCL generation is
deterministic (renderers in `hopshift/targets/<name>/` driven by the CIM; `generation.mode: deterministic`).
LLM calls are optional and happen in at most two places: HCL generation in `llm`/`hybrid`
mode and review-note writing. All other logic is deterministic Python.
When in doubt about whether something should use an LLM: it should not.

## The transformation pipeline
discovery JSON → [ingest] → [blocker check] → [enrich] → [translate: source plugin] → CIM → [size] → [MCP docs] → [HCL gen: target plugin] → [validate] → output/

The CIM (Canonical Infrastructure Model) is the central artifact. It is the contract
between every source and every target. Never bypass it. Sources and targets are plugins
resolved through registries; nothing downstream of the CIM may know a source field name and
nothing upstream of it may know a target resource type.

## Key files to read before coding
- `docs/architecture.md`: the map: sources, CIM, targets, registries, pipeline, platform services, API, UI, storage, threat model
- `docs/plugins.md`, `docs/support-matrix.md`: the plugin contract and the tiers
- `hopshift/cim/schema.py`: all data models before touching any node (CIM 1.1; regenerate `cim.schema.json` with `python -m hopshift.cim.schema_export`)
- `hopshift/cim/blockers.py`: the canonical blocker vocabulary, keyed by source platform
- `hopshift/sources/registry.py`, `hopshift/sources/__init__.py`: `SourceSpec`, the source registry and the built-in VMware source (`hopshift/sources/vmware.py`)
- `hopshift/targets/registry.py`, `hopshift/targets/__init__.py`: `TargetSpec`, the target registry and the built-in targets
- `hopshift/targets/common.py`, `hopshift/targets/runtime_common.py`: escaping, naming and variable helpers every renderer must use
- `hopshift/pipeline/generation/deterministic.py`: how renderer output is assembled into a flat root module
- `hopshift/pipeline/state.py`: MigrationState before touching the graph
- `hopshift/pipeline/graph.py`: the full node graph before adding nodes
- `hopshift/pipeline/runtime.py`: the run service layer (create/start/pause/resume/rerun/cancel/delete)
- `hopshift/services/platform.py`: how platform services (db, secrets, audit, settings, security, connections, deploy) are wired
- `hopshift/api/deps.py`, `hopshift/api/app.py`: principal/roles and the app factory; one router per area in `hopshift/api/routes/`
- `config.yaml`: all runtime config lives here (security, deploy, runtime sections included)

## Design decisions already made: do not revisit
1. LangGraph (not CrewAI) for orchestration
2. Swappable LLM via LLMClient abstraction (Anthropic / OpenAI / Google)
3. 1:1 virtual switch topology reconstruction (not flattened)
4. Clusters map to target-native placement through the ClusterSemantics enum
5. Temperature 0.0 for HCL generation (deterministic output)
6. OPA for security and compliance policy enforcement (not ad-hoc checks); controls carry CIS / SOC 2 / HIPAA references
7. Output to output/ directory; deployments run from a copy of the artifacts, never in place
8. Pydantic v2 for all models; Click for CLI; FastAPI for the API; SQLite (WAL) for platform state
9. Platform services live in `hopshift/services/` and attach through `build_<service>_service(platform)`; services raise `hopshift.services.errors` exceptions, the API maps them
10. Secrets are encrypted at rest with Fernet keys from the environment (`HOPSHIFT_SECRET_KEY`); never stored or logged in clear
11. Every mutating action is written to the hash-chained audit log with actor, IP and user agent
12. UI: React 19 + Vite + Tailwind v4 + Radix primitives owned in-repo (no component framework); hash routes; talks only to `/api`
13. Sources and targets are registry entries (`SourceSpec`, `TargetSpec`) discovered through the entry-point groups `hopshift.sources` and `hopshift.targets`; `TargetProvider` is a normalised string, not an enum. The deterministic path resolves everything through the registries; target names are hardcoded only in the `llm`/`hybrid` path, the policies and the connections catalog

## Non-negotiable security rules
Generated Terraform:
- No public S3 buckets / public storage; no 0.0.0.0/0 ingress; no management ports open to the Internet
- Encrypted VMs are quarantined, not migrated
- All generated resources carry Environment, Owner, MigratedFrom tags
- No code-execution constructs: provisioner blocks, external/http data sources, null_resource, local_file.
  Module sources must be local `./` paths and provider sources must be on the per-target allow-list in
  `hopshift/pipeline/nodes/hcl_generator.py`
- Generated file paths are validated (no absolute paths, no `..`); workload names are sanitized before they become file names,
  and every string from discovery goes through `hcl_string` in `hopshift/targets/common.py` so it cannot open a template expression
- The reporter always runs; unvalidated HCL is never written to output/; the CLI exits non-zero when the run did not succeed
- Renderers stay compliant with every `enforce` control in `hopshift/validation/policies/compliance/` (the integration suite checks this)

Platform:
- Authentication is required by default; `security.auth.mode: disabled` is for local development only
- Role checks on every mutating route (`hopshift.api.deps.require_role`); viewers read, operators run and approve, admins manage
- Apply and destroy need a succeeded, unchanged plan and a typed confirmation; both actions can be disabled globally
- Secret values never appear in API responses, logs, audit details or deployment logs (mask with `hopshift.services.secrets.mask_values`)
- Keep the security headers, CSP and origin checks in `hopshift/api/middleware.py`; no inline scripts in the UI

## How to add a new resource type
1. Add the Pydantic model to `hopshift/cim/schema.py`
2. Add the translation logic to every source (`hopshift/sources/vmware.py` today)
3. Add the rendering to every target package under `hopshift/targets/<name>/`
4. Add an OPA policy if the resource has security implications
5. Regenerate `hopshift/cim/cim.schema.json` with `python -m hopshift.cim.schema_export`

## Runtime, API and UI
- `hopshift/pipeline/runtime.py` is the service layer (runs, pause points, state patching, re-run, cancel, delete); the CLI and the
  API both use it. `hopshift/api/app.py` is a factory (no module-level app); serve with `hopshift serve` or `uvicorn --factory hopshift.api.app:create_app`.
- Platform services: `hopshift/services/security` (users, sessions, tokens, MFA, OIDC, lockout, retention, posture), `hopshift/services/connections`
  (catalog, verification, Terraform credentials, device flows), `hopshift/services/deploy` (terraform plan/apply/destroy with gates),
  `hopshift/services/compliance` (control catalog and report), `hopshift/services/audit.py`, `secrets.py`, `settings.py`, `db.py`.
- `GET /api/meta` exposes the registered targets and sources; clients build their target choices from it.
- The React UI lives in `ui/` and is served from `ui/dist` by the API. UI checks: `npx tsc --noEmit`, `npx vitest run`,
  `npm run build`, `npx playwright test` (starts an isolated server through `ui/e2e/serve.py`).

## How to add a new source
Full guide: `docs/plugins.md`. In short:
1. Write a translator `translate(discovery_data, target) -> CanonicalInfrastructureModel`; set `source.platform` and each
   ComputeUnit's `architecture`
2. Register a `SourceSpec` (name, schema names, translator, platform, tier, collector, docs) in `hopshift/sources/__init__.py`
   for a built-in source, or expose it through a `hopshift.sources` entry point for an external package
3. Extend `hopshift/cim/blockers.py` with the platform's flag-to-blocker table if its flags differ
4. Add a fixture under `tests/fixtures/`, a translator test, and `docs/sources/<name>.md`; renderers and policies need no change

## How to add a new target
Full guide: `docs/plugins.md`. In short:
1. Create a package with `network.py`, `compute.py`, `storage.py`, `placement.py`, `runtime.py` and `sizing_table.py`
   (`render_networking`, `render_compute`, `render_storage`, `render_placement`, `render_runtime`, `get_instance_type`);
   renderers emit logical keys `<name>-migration/<resource_type>/<file>.tf` and the assembler flattens them
2. Register a `TargetSpec` (name, label, blurb, package, tier, tflint, connection_provider, architectures, docs) in
   `hopshift/targets/__init__.py` for a built-in target, or expose it through a `hopshift.targets` entry point
3. Use `hopshift/targets/common.py` for every name and string from the CIM; emit the required tags with `var.environment` / `var.owner`
4. For deployments add the connections catalog entries in `hopshift/services/connections/models.py`; for compliance add Rego rules
   under `hopshift/validation/policies/compliance/` and `Control` entries in `hopshift/services/compliance/controls.py`
5. Add an integration test case in `tests/integration/` and `docs/targets/<name>.md`; the tier in `docs/support-matrix.md` follows the evidence

## Testing expectations
- Every node function has a unit test in `tests/nodes/`; the graph and runtime in `tests/pipeline/`; platform services in `tests/services/`;
  HTTP in `tests/api/`; renderer helpers in `tests/targets/`; the assembler in `tests/generation/`
- CIM translation has property-based tests (hypothesis) in `tests/cim/`
- Sizing lookup has parametrized tests covering edge cases (exact match, ceiling, max)
- OPA policies evaluate parsed HCL (see `hopshift/validation/hcl_parser.py`); policy tests in `tests/validation/` run the real `opa` binary
- `tests/integration/` renders every built-in target and runs real terraform validate + tflint + OPA, and asserts zero enforce violations
- Cloud SDK calls and the terraform binary are stubbed in unit tests (`tests/fixtures/fake_terraform.sh`)
- No tests write to `output/`; use the `tmp_path` pytest fixture
- `ruff check .` must be clean; line endings are LF everywhere (`.gitattributes`)
