# Phase 3 — the migration platform

This document is the build contract for phase 3. It describes the target architecture, the
API surface, the data model and the work breakdown. Each workstream below is self-contained
and must be implementable from this document plus the code it points at.

## Goals

1. A UI people enjoy: minimalist, fast, keyboard friendly, dark and light themes, smooth motion.
2. A platform, not a tool: accounts, roles, audit, cloud connections, plan and apply with gates.
3. Secure and compliant by construction: the technical controls that SOC 2, HIPAA and CIS audits
   look for are built in and produce evidence (audit chain, compliance reports, posture checks).
4. Public-ready repository: README, architecture docs, setup guides, CI, security policy, MIT.

Non-goals: SOC 2 or HIPAA *certification* (organisational attestations outside any codebase),
a hosted multi-tenant service, and migration of disk images themselves (the platform generates
and applies the infrastructure; image import is referenced through `image_overrides`).

## Architecture (target state)

```
┌──────────────────────────── ui/ (React 19, Vite, Tailwind v4, Radix, motion) ────────────────────────────┐
│ Login/Setup · Dashboard · Runs · New run wizard · Run detail (timeline, CIM, artifacts, deploy,            │
│ compliance, log) · Assess · Connections · Settings (general, users, tokens, audit, posture, profile)       │
└──────────────────────────────────────────────┬───────────────────────────────────────────────────────────┘
                                               │ /api (JSON + SSE), cookie session or bearer token
┌──────────────────────────────────────────────▼───────────────────────────────────────────────────────────┐
│ api/            FastAPI app factory, routers per area, deps (principal, roles), middleware (headers, CSRF) │
│ vma/            platform services                                                                         │
│   platform.py   Platform container: config, db, secrets, audit, settings, auth, connections, deployments  │
│   db.py         SQLite (WAL) + migration registry            secrets.py  Fernet box, key from env         │
│   audit.py      hash-chained audit log                        settings.py editable config overlay         │
│   security/     users, sessions, API tokens, RBAC, TOTP MFA, OIDC SSO, lockout, headers, retention        │
│   connections/  cloud connections: catalog of auth methods, verification, credential resolution           │
│   deploy/       terraform init/plan/apply/destroy executor with streaming logs and approval gates         │
│   compliance/   compliance report (controls → CIS / SOC 2 / HIPAA mapping) from OPA results               │
│ agent/          LangGraph pipeline + MigrationRuntime (runs, pause/resume/rerun, cancel)                   │
│ cim/ providers/ validation/   unchanged responsibilities; renderers hardened to pass compliance policies   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
Storage: output/runs/<run_id>/ (run.json, discovery.json, events.jsonl, artifacts/, deploy/)
         output/platform.sqlite (users, sessions, tokens, connections, audit_log, settings, deployments)
         output/runs/checkpoints.sqlite (LangGraph checkpoints)
```

Principles kept from earlier phases: the deterministic core generates and validates; the LLM
is optional at the edges; every write path goes through `MigrationRuntime`; CRLF line endings
are preserved on files that already use them.

## Platform core (owned by the integrator, already in place)

- `vma/db.py` — `Database(path)`, `with db.connect() as conn`, `register_migration(name, sql)`,
  `db.migrate()`. Every service registers its own tables at import time.
- `vma/secrets.py` — `SecretBox.from_env()` reads `HOPSHIFT_SECRET_KEY` (one or more comma-separated
  Fernet keys, first is primary). `encrypt_json` / `decrypt_json` / `rotate` / `generate_key()`.
  `available` is false without a key; services must refuse to store secrets in that case and
  explain how to set the key.
- `vma/audit.py` — `AuditLog.record(action, actor=..., actor_kind=..., target_type=..., target_id=...,
  outcome=..., details=..., ip=..., user_agent=...)`. Entries are hash-chained
  (`hash = sha256(prev_hash + canonical_json(entry))`). `list(...)`, `verify()`, `iter_all()`.
  Never put secrets in `details`.
- `vma/settings.py` — editable overlay stored in SQLite and applied over `config.yaml`
  (`EDITABLE_SETTINGS` is the allow-list; everything else is file-only).
- `vma/platform.py` — `Platform.from_config(config)` wires the services. Optional services are
  attached by `build_auth_service(platform)`, `build_connection_service(platform)` and
  `build_deploy_service(platform)` when their packages exist.
- `api/deps.py` — `Principal`, `current_principal`, `require_role("viewer"|"operator"|"admin")`,
  `get_platform`, `get_runtime`, `audit_context(request)`.
- `api/app.py` + `api/routes/*.py` — one router per area. Add a router by creating
  `api/routes/<area>.py` exposing `router = APIRouter()` and listing it in `api/routes/__init__.py`.

Roles: `viewer` reads runs, artifacts, connections (metadata only). `operator` adds run
mutations, approvals, plan/apply/destroy, connection tests. `admin` adds users, tokens for others,
connection management, settings, the audit log.

## Workstream A — security (`vma/security/`, `api/routes/auth.py`, `users.py`, `audit.py`)

Users with argon2id password hashes, sessions (random 256-bit token, stored hashed, absolute and
idle expiry, cookie `hopshift_session` HttpOnly SameSite=Lax, `Secure` on https), API tokens
(`hs_` prefix, stored hashed, role, optional expiry, last used), RBAC, TOTP MFA with recovery
codes (policy `optional` or `required`), OIDC SSO (discovery, PKCE, nonce, JWKS verification,
domain/group to role mapping), login lockout (per user) and per-IP throttling, security headers
middleware (CSP, HSTS on https, frame deny, nosniff, referrer policy, permissions policy),
origin check for cookie-authenticated mutations, run and audit retention sweeps, and the
`/settings/posture` checks. First-run setup creates the first admin when no users exist.

Endpoints: see "API surface". CLI: `vma admin create-user`, `vma admin reset-password`,
`vma secrets generate-key`, `vma secrets rotate`, `vma audit verify`, `vma runs prune`.

## Workstream B — cloud connections (`vma/connections/`, `api/routes/connections.py`)

A connection is `{id, name, provider, auth_method, config (non-secret), secret (encrypted),
status, last_checked_at, last_check, created_by, created_at, updated_at}`.

Auth methods (the catalog endpoint describes the fields so the UI renders forms generically):

| provider | methods |
|---|---|
| aws | `access_keys` (key id, secret, optional session token, region), `profile` (named profile from a mounted `~/.aws`), `assume_role` (base: keys, profile or environment; role ARN, external id, session name), `environment` (instance role, IRSA, env vars), `sso` (device authorization through sso-oidc: start URL, region, account, role), `web_identity` (role ARN + token file). Optional `endpoint_url` for LocalStack or private endpoints. |
| azure | `service_principal_secret` (tenant, client id, secret), `service_principal_certificate` (PEM), `managed_identity` (optional client id), `oidc` (workload identity federation token), `cli` (mounted `~/.azure`), `device_code` (interactive sign-in; verification only, Terraform needs one of the others). Always `subscription_id`. |
| gcp | `service_account_key` (JSON), `adc` (application default credentials / metadata server), `impersonation` (base credentials + target service account), `workload_identity_federation` (external account JSON). Always `project_id`, optional `region`. |
| openstack | `password` (auth URL, user, password, project, domains), `application_credential` (id + secret), `clouds_yaml` (cloud name from a mounted `clouds.yaml`). |

`verify(connection)` returns the identity (account id and ARN, tenant and subscription name,
project id and principal, Keystone project) using boto3, azure-identity + ARM REST, google-auth +
Resource Manager REST, Keystone REST. `terraform_env(connection)` resolves credentials into the
environment variables Terraform providers read (`AWS_*`, `ARM_*`, `GOOGLE_*`, `OS_*`); assume-role
and SSO resolve to temporary credentials first. Secrets never leave the service: API responses
expose `has_secret` and field names only.

## Workstream C — deployments (`vma/deploy/`, `api/routes/deploy.py`)

`DeployService` runs Terraform in the run's root module (`artifacts/<cloud>-migration/`) with the
environment from a connection. Actions: `plan` (init, plan `-out=tfplan -detailed-exitcode`, `show
-json`), `apply` (requires a succeeded plan id and `confirmation == run_id`), `destroy` (same
confirmation). Each deployment is a record under `output/runs/<run_id>/deploy/<deployment_id>/`
(`deployment.json`, `terraform.log`, `plan.json`) and a row in SQLite for listing. Logs stream as
lines; secret values from the connection are masked in the log. Variables for the root module are
parsed from `variables.tf` (`GET .../deploy/variables`) and written to `terraform.tfvars.json`.
State stays local in the root module unless `deploy.remote_state` is configured, in which case a
`backend.tf` is written. Cancel terminates the process. `deploy.allow_apply` and
`deploy.allow_destroy` gate the actions globally.

## Workstream D — compliance (`hopshift/validation/policies/compliance/`, `vma/compliance/`, renderers)

OPA policies with explicit control metadata, evaluated in the validator alongside the existing
rules. Controls have a level: `enforce` (fails the gate) or `advisory` (reported only). The
validator stores `compliance_result` in state and the reporter writes `compliance_report.json`
and `compliance_report.md` next to the HCL. Each control carries CIS Benchmark, SOC 2 TSC and
HIPAA Security Rule references. Renderers are hardened so the deterministic output passes every
`enforce` control on all four clouds (IMDSv2, encrypted volumes, no public IPs, locked-down
default security groups, OS Login, shielded VMs, no IP forwarding, subnet flow logs, TLS-only
storage, and so on). The integration tests (real `terraform validate`) stay green.

## Workstream E — UI (`ui/`)

Tailwind v4, Radix primitives, `motion`, lucide icons, cmdk palette, TanStack table and virtual,
shiki for HCL, recharts for analytics. Pages: setup, login (password, TOTP step, SSO button),
dashboard, runs (filters, search, tags, cancel, delete), new run wizard (upload → options →
connection → review → start), run detail (timeline with live events, overview, CIM table with
inline edits, blocker badges and bulk actions, artifacts with file tree, highlighting, diff against
another run and zip download, deploy panel with variables, plan summary, streaming log and typed
confirmation, compliance tab, log tab), assess (readiness charts, per-VM table, CSV and Markdown
export), connections (list, generic form from the catalog, test, device-code flow), settings
(general, users, tokens, audit, posture, profile with password and MFA), keyboard shortcuts.

## Workstream F — repository (README, docs, CI, publication)

README with hero, badges, features, quickstart, screenshots. `docs/architecture.md`,
`docs/setup.md`, `docs/security.md`, `docs/compliance.md`, `docs/connections.md`,
`docs/deployments.md`, refreshed existing docs. CONTRIBUTING, SECURITY.md, CODE_OF_CONDUCT,
LICENSE (MIT), issue and PR templates, Dependabot, CI (ruff, pytest with terraform/tflint/opa,
vitest, playwright, pip-audit, npm audit, gitleaks, trivy image scan, CodeQL). Merge the phase
branches into `main`, then flip the repository to public.

## API surface (all paths under `/api`)

Auth and principal: cookie session or `Authorization: Bearer hs_...`.

```
GET  /auth/status                      public: {setup_required, auth_mode, oidc_enabled, mfa_policy, user?}
POST /auth/setup                       public while no users exist: {username, password, name}
POST /auth/login                       {username, password, totp_code?} → user or 401 / {mfa_required: true}
POST /auth/logout
GET  /auth/me
POST /auth/password                    {current_password, new_password}
POST /auth/mfa/enroll                  → {secret, otpauth_uri}
POST /auth/mfa/confirm                 {code} → {recovery_codes}
POST /auth/mfa/disable                 {password, code}
GET  /auth/oidc/login                  302 to the identity provider
GET  /auth/oidc/callback               302 to /#/ with a session
GET  /auth/tokens  POST /auth/tokens {name, role?, expires_days?} → {id, token}   DELETE /auth/tokens/{id}
GET  /users  POST /users  PATCH /users/{id}  DELETE /users/{id}  POST /users/{id}/mfa/reset      (admin)
GET  /audit?limit&offset&action&actor&since&target_id → {entries, total}   GET /audit/verify   GET /audit/export (admin)

GET  /health   GET /meta (adds version, auth_mode, features)   GET /config (admin)
GET  /dashboard                        counts by status and cloud, recent runs, 30-day series
GET  /runs  POST /runs (+ name, tags, connection_id)   GET /runs/{id}   PATCH /runs/{id} {name, tags, connection_id}
DELETE /runs/{id}   POST /runs/{id}/start|resume|cancel   POST /runs/{id}/rerun {node}
GET  /runs/{id}/state   PATCH /runs/{id}/state {values}
GET  /runs/{id}/events?since   GET /runs/{id}/events/stream (SSE)
GET  /runs/{id}/artifacts   GET /runs/{id}/artifacts/{path}   GET /runs/{id}/artifacts/archive (zip)
GET  /runs/{id}/diff/{other_id}        per-file unified diffs of the generated root modules
GET  /runs/{id}/compliance             compliance report
POST /assess {discovery, cloud}

GET  /connections/methods              catalog: provider → auth methods → field specs
GET  /connections   POST /connections {name, provider, auth_method, config, secret}
GET  /connections/{id}   PATCH /connections/{id}   DELETE /connections/{id}   POST /connections/{id}/test
POST /connections/{id}/device/start → {flow_id, user_code, verification_uri, verification_uri_complete, expires_in, interval}
POST /connections/{id}/device/poll {flow_id} → {status: pending|complete|expired|error, message}

GET  /runs/{id}/deployments   POST /runs/{id}/deployments {action, connection_id, plan_id?, confirmation?} → 202
GET  /runs/{id}/deployments/{dep_id}   GET .../log?since   GET .../log/stream (SSE)   GET .../plan   POST .../cancel
GET  /runs/{id}/deploy/variables   PUT /runs/{id}/deploy/variables {values}   GET /runs/{id}/deploy/state

GET  /settings → {effective, overrides, schema}   PUT /settings {values}   GET /settings/posture
```

Errors: `RunError` → 404 for unknown runs, otherwise 400; validation errors 400; auth 401;
authorization 403; conflicts 409. Bodies are plain text or `{"detail": ...}`.

## Data model additions

- `RunRecord`: `name`, `tags`, `connection_id`, `created_by`, `cancel_requested`; statuses gain
  `cancelled`.
- SQLite tables: `users`, `sessions`, `api_tokens`, `mfa_recovery_codes`, `oidc_states`,
  `login_attempts`, `connections`, `device_flows`, `deployments`, `audit_log`, `settings`.

## Configuration additions (`config.yaml`)

```yaml
security:
  auth:
    mode: required            # required | disabled (disabled is for local development only)
    session_hours: 12
    idle_minutes: 60
    mfa: optional             # optional | required
    lockout_threshold: 5
    lockout_minutes: 15
    oidc:
      enabled: false
      issuer: ""
      client_id: ""
      client_secret_env: HOPSHIFT_OIDC_CLIENT_SECRET
      scopes: [openid, profile, email]
      allowed_domains: []
      default_role: viewer
      admin_groups: []
      groups_claim: groups
  secret_key_env: HOPSHIFT_SECRET_KEY
  headers:
    hsts: true
    content_security_policy: default
  retention:
    runs_days: 0              # 0 keeps everything
    audit_days: 0
  encrypt_run_inputs: false   # store discovery.json encrypted with the secret key
deploy:
  terraform_bin: terraform
  timeout_minutes: 60
  allow_apply: true
  allow_destroy: true
  remote_state:
    enabled: false
    type: ""                  # s3 | azurerm | gcs
    config: {}
```

## Testing strategy

- Python unit tests per service with SQLite in `tmp_path`; cloud SDK calls are stubbed; the
  Terraform executor is tested with a fake `terraform` script on `PATH`.
- Integration tests keep running real `terraform validate`, tflint and OPA on all four clouds.
- Vitest for UI components and hooks with a mocked API; Playwright end-to-end against the real
  server: setup → login → connection (fake terraform) → run → CIM edit → approvals → plan → apply.
- A LocalStack recipe in the docs for a real AWS plan and apply without an account.
