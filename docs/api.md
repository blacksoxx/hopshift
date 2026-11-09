# HTTP API

All endpoints live under `/api`. Interactive documentation is served at `/docs` (Swagger UI)
unless `security.api_docs` is false. Responses are JSON; errors are plain text or
`{"detail": ...}` with the status codes below.

| Status | Meaning |
|---|---|
| 400 | invalid request or lifecycle state (`vma.errors.Invalid`, `RunError`) |
| 401 | authentication required or credentials invalid |
| 403 | role too low, confirmation missing, action disabled, origin check failed |
| 404 | unknown run, connection, deployment, user |
| 409 | conflict (duplicate name, run already executing, active deployment) |
| 422 | body validation (pydantic) |
| 429 | login throttled (`Retry-After` header) |
| 503 | a required key or backend is missing (`vma.errors.Unavailable`) |

## Authentication

Send either the session cookie set by `POST /api/auth/login` (browser) or an API token:

```
Authorization: Bearer vma_...
```

Cookie-authenticated mutations must come from the same origin (or one listed in
`security.allowed_origins`). Roles: `viewer` < `operator` < `admin`. With
`security.auth.mode: disabled` every caller is an anonymous admin (development only).

## Endpoints

### Auth and account

| Method and path | Role | Notes |
|---|---|---|
| `GET /auth/status` | public | `{setup_required, auth_mode, oidc_enabled, mfa_policy, user?}` |
| `POST /auth/setup` | public, only while no users exist | `{username, password, name}` creates the first admin |
| `POST /auth/login` | public | `{username, password, totp_code?}`; `401 {"detail":"mfa_required","mfa_required":true}` when a code is needed |
| `POST /auth/logout` | any | revokes the session |
| `GET /auth/me` | any | current user |
| `POST /auth/password` | any | `{current_password, new_password}`; revokes other sessions |
| `POST /auth/mfa/enroll` | any | `{secret, otpauth_uri}` |
| `POST /auth/mfa/confirm` | any | `{code}` → `{recovery_codes}` |
| `POST /auth/mfa/disable` | any | `{password, code}` |
| `GET /auth/oidc/login` | public | redirect to the identity provider |
| `GET /auth/oidc/callback` | public | completes sign-in, redirects to `/#/` |
| `GET /auth/tokens` · `POST /auth/tokens` · `DELETE /auth/tokens/{id}` | any (own); admin with `?all=true` | `POST {name, role?, expires_days?}` → `{id, token}` shown once |

### Users and audit (admin)

| Method and path | Notes |
|---|---|
| `GET /users` · `POST /users` · `PATCH /users/{id}` · `DELETE /users/{id}` | `{username, password, name, role}`; cannot delete yourself or the last admin |
| `POST /users/{id}/mfa/reset` | clears the second factor |
| `GET /audit?limit&offset&action&actor&since&target_id&target_type&outcome` | `{entries, total}` |
| `GET /audit/verify` | `{ok, entries, broken_at, message}` |
| `GET /audit/export` | ndjson |

### Meta and settings

| Method and path | Role | Notes |
|---|---|---|
| `GET /health` | public | `{ok, runs_dir, version}` |
| `GET /meta` | any | clouds, modes, pause points, nodes, defaults, `auth_mode`, `features` |
| `GET /config` | admin | effective configuration (file + overrides) |
| `GET /dashboard` | viewer | counts by status and cloud, success rate, 30-day series, recent and paused runs |
| `GET /settings` | admin | `{effective, overrides, schema}` |
| `PUT /settings` | admin | `{values: {"dotted.key": value}}`; `null` removes an override |
| `GET /settings/posture` | viewer | live security posture checks |

### Runs

| Method and path | Role | Notes |
|---|---|---|
| `GET /runs?status&cloud&tag&q` | viewer | list, newest first |
| `POST /runs` | operator | `{discovery, options, input_filename?, start?, name?, tags?, connection_id?}` → 201 |
| `GET /runs/{id}` | viewer | record plus `executing` |
| `PATCH /runs/{id}` | operator | `{name?, tags?, connection_id?, clear_connection?}` |
| `DELETE /runs/{id}` | operator | refuses while executing or deploying |
| `POST /runs/{id}/start` · `/resume` · `/cancel` | operator | 202; resume approves the current pause point |
| `POST /runs/{id}/rerun` | operator | `{node}` re-runs from the checkpoint before that node |
| `GET /runs/{id}/state` | viewer | graph state (CIM, quarantine, validation, compliance) |
| `PATCH /runs/{id}/state` | operator | `{values: {sized_cim | cim | quarantine_queue}}` while paused |
| `GET /runs/{id}/events?since` | viewer | events; `GET /runs/{id}/events/stream` is the SSE version (`event: done` at the end) |
| `GET /runs/{id}/artifacts` · `/artifacts/{path}` · `/artifacts/archive` | viewer | list, file text, zip |
| `GET /runs/{id}/diff/{other_id}` | viewer | unified diffs of the generated `.tf` files |
| `GET /runs/{id}/compliance` | viewer | the compliance report |
| `POST /assess` | viewer | `{discovery, cloud}` → readiness assessment, synchronous |

`options` mirrors the CLI: `cloud`, `environment`, `owner`, `mode`, `llm_provider`,
`llm_model`, `llm_base_url`, `skip_validation`, `skip_opa`, `no_mcp`, `dry_run`,
`llm_review_notes`, `pause_points` (omit for the configured defaults, `[]` for none).

### Connections

| Method and path | Role | Notes |
|---|---|---|
| `GET /connections/methods` | viewer | catalog: provider → methods → field specs |
| `GET /connections?provider=` · `GET /connections/{id}` | viewer | public view (never secret values) |
| `POST /connections` | admin | `{name, provider, auth_method, config, secret}` → 201 |
| `PATCH /connections/{id}` | admin | `{name?, config?, secret?}` (partial secret merge) |
| `DELETE /connections/{id}` | admin | |
| `POST /connections/{id}/test` | operator | `{ok, identity, message, checked_at}` |
| `POST /connections/{id}/device/start` · `/device/poll` | operator | device-code sign-in (AWS SSO, Azure) |

### Deployments

| Method and path | Role | Notes |
|---|---|---|
| `GET /runs/{id}/deployments` | viewer | history |
| `POST /runs/{id}/deployments` | operator | `{action: plan|apply|destroy, connection_id, plan_id?, confirmation?}` → 202; apply needs a succeeded, unchanged plan and `confirmation == run id`; destroy needs the confirmation |
| `GET /runs/{id}/deployments/{dep}` | viewer | record with summary |
| `GET .../log?since` · `GET .../log/stream` | viewer | masked log lines; SSE variant |
| `GET .../plan` | viewer | `terraform show -json` output (sensitive values blanked) |
| `POST .../cancel` | operator | terminates the process |
| `GET /runs/{id}/deploy/variables` · `PUT` | viewer / operator | variables parsed from `variables.tf`; `PUT {values}` writes `terraform.tfvars.json` |
| `GET /runs/{id}/deploy/state` | viewer | summary of the Terraform state |

## Server-sent events

Both streams emit `data: <json>` messages, `: keep-alive` comments every few seconds and a
final `event: done` with `{"status": ...}`. Reconnect with `?since=<count>` to resume.
