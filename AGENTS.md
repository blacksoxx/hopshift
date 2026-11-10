# AGENTS.md — Project context for AI coding assistants

This file is read by Claude Code, Cursor, Copilot, and any other AI coding tool
working in this repository. It is the authoritative source of project intent,
constraints, and design decisions.

## Project purpose
Convert VMware vSphere discovery JSON (produced by an Ansible collection) into deployable,
compliant Terraform for a target cloud (AWS, Azure, GCP, OpenStack), let humans review and
approve it, and deploy it through stored cloud connections. Ships as a CLI (`vma`), an HTTP
API and a web UI; runs in CI or as a container.

## Core constraint
This is a data transformation pipeline, not a chatbot. Default HCL generation is
deterministic (templates in `providers/` driven by the CIM; `generation.mode: deterministic`).
LLM calls are optional and happen in at most two places: HCL generation in `llm`/`hybrid`
mode and review-note writing. All other logic is deterministic Python.
When in doubt about whether something should use an LLM — it should not.

## The transformation pipeline
VMware JSON → [ingest] → [blocker check] → [enrich] → CIM → [size] → [RAG] → [HCL gen] → [validate] → output/

The CIM (Canonical Infrastructure Model) is the central artifact. It is the contract
between the VMware world and the cloud provider world. Never bypass it.

## Key files to read before coding
- `docs/architecture.md`      — the map: pipeline, platform services, API, UI, storage, threat model
- `docs/platform-plan.md`     — the phase-3 build contract (API surface, data model, workstreams)
- `cim/schema.py`             — all data models before touching any node (CIM 1.1; regenerate cim.schema.json with `python -m hopshift.cim.schema_export`)
- `cim/translators/`          — one translator per source hypervisor, selected by discovery schema_name
- `agent/state.py`            — MigrationState before touching the graph
- `agent/graph.py`            — the full node graph before adding nodes
- `agent/runtime.py`          — the run service layer (create/start/pause/resume/rerun/cancel/delete)
- `providers/base.py`         — the ProviderModule interface before adding a provider
- `vma/platform.py`           — how platform services (db, secrets, audit, settings, security, connections, deploy) are wired
- `api/deps.py`, `api/app.py` — principal/roles and the app factory; one router per area in `api/routes/`
- `config.yaml`               — all runtime config lives here (security, deploy, runtime sections included)

## Design decisions already made — do not revisit
1. LangGraph (not CrewAI) for orchestration
2. Swappable LLM via LLMClient abstraction (Anthropic / OpenAI / Google)
3. 1:1 vDS topology reconstruction (not flattened)
4. DRS clusters map to cloud-native equivalents via ClusterSemantics enum
5. Temperature 0.0 for HCL generation (deterministic output)
6. OPA for security and compliance policy enforcement (not ad-hoc checks); controls carry CIS / SOC 2 / HIPAA references
7. Output to output/ directory; deployments run from a copy of the artifacts, never in place
8. Pydantic v2 for all models; Click for CLI; FastAPI for the API; SQLite (WAL) for platform state
9. Platform services live in `vma/` and attach through `build_<service>_service(platform)`; services raise `vma.errors` exceptions, the API maps them
10. Secrets are encrypted at rest with Fernet keys from the environment (`HOPSHIFT_SECRET_KEY`); never stored or logged in clear
11. Every mutating action is written to the hash-chained audit log with actor, IP and user agent
12. UI: React 19 + Vite + Tailwind v4 + Radix primitives owned in-repo (no component framework); hash routes; talks only to `/api`

## Non-negotiable security rules
Generated Terraform:
- No public S3 buckets / public storage; no 0.0.0.0/0 ingress; no management ports open to the Internet
- Encrypted VMs are quarantined, not migrated
- All generated resources carry Environment, Owner, MigratedFrom tags
- No code-execution constructs: provisioner blocks, external/http data sources, null_resource, local_file.
  Module sources must be local `./` paths and provider sources must be on the per-cloud allow-list in
  `agent/nodes/hcl_generator.py`
- Generated file paths are validated (no absolute paths, no `..`); VM names are sanitized before they become file names
- The reporter always runs; unvalidated HCL is never written to output/; the CLI exits non-zero when the run did not succeed
- Renderers stay compliant with every `enforce` control in `hopshift/validation/policies/compliance/` (the integration suite checks this)

Platform:
- Authentication is required by default; `security.auth.mode: disabled` is for local development only
- Role checks on every mutating route (`api.deps.require_role`); viewers read, operators run and approve, admins manage
- Apply and destroy need a succeeded, unchanged plan and a typed confirmation; both actions can be disabled globally
- Secret values never appear in API responses, logs, audit details or deployment logs (mask with `vma.secrets.mask_values`)
- Keep the security headers, CSP and origin checks in `api/middleware.py`; no inline scripts in the UI

## How to add a new resource type
1. Add the Pydantic model to `cim/schema.py`
2. Add the translation logic to `cim/vmware_translator.py`
3. Add a new file per provider in each `providers/{provider}/` subpackage
4. Add an OPA policy if the resource has security implications
5. Regenerate `hopshift/cim/cim.schema.json` with `python -m hopshift.cim.schema_export`

## Runtime, API and UI
- `agent/runtime.py` is the service layer (runs, pause points, state patching, re-run, cancel, delete); the CLI and the
  API both use it. `api/app.py` is a factory (no module-level app); serve with `vma serve` or `uvicorn --factory hopshift.api.app:create_app`.
- Platform services: `vma/security` (users, sessions, tokens, MFA, OIDC, lockout, retention, posture), `vma/connections`
  (catalog, verification, Terraform credentials, device flows), `vma/deploy` (terraform plan/apply/destroy with gates),
  `vma/compliance` (control catalog and report), `vma/audit.py`, `vma/secrets.py`, `vma/settings.py`, `vma/db.py`.
- The React UI lives in `ui/` and is served from `ui/dist` by the API. UI checks: `npx tsc --noEmit`, `npx vitest run`,
  `npm run build`, `npx playwright test` (starts an isolated server through `ui/e2e/serve.py`).

## How to add a new source hypervisor
1. Write `cim/translators/<platform>.py` producing the CIM; set `source.platform` and each
   ComputeUnit's `architecture`
2. Register it in `cim/translators/__init__.py` under the collector's `metadata.schema_name`
3. Extend `cim/blockers.py` with the platform's flag-to-blocker table if its flags differ
4. Add a fixture under `tests/fixtures/` and a translator test; renderers and policies need no change

## How to add a new cloud provider
1. Create `providers/{name}/` with compute.py, network.py, storage.py, sizing_table.py
2. Implement the `ProviderModule` abstract base class from `providers/base.py`
3. Register the provider in `agent/llm_client.py` provider routing
4. Add sizing anchors to sizing_table.py
5. Add provider to the `target_cloud` enum in config.yaml comments

## Testing expectations
- Every node function has a unit test in `tests/nodes/`; platform services in `tests/vma/`; HTTP in `tests/api/`
- CIM translation has property-based tests (hypothesis) in `tests/cim/`
- Sizing lookup has parametrized tests covering edge cases (exact match, ceiling, max)
- OPA policies evaluate parsed HCL (see `validation/hcl_parser.py`); policy tests in `tests/validation/` run the real `opa` binary
- `tests/integration/` renders every cloud and runs real terraform validate + tflint + OPA, and asserts zero enforce violations
- Cloud SDK calls and the terraform binary are stubbed in unit tests (`tests/fixtures/fake_terraform.sh`)
- No tests write to `output/` — use the `tmp_path` pytest fixture
- `ruff check .` must be clean; line endings are LF everywhere (`.gitattributes`)
