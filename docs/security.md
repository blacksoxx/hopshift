# Security

This page describes the access-control and hardening features of the platform (workstream A of
`docs/platform-plan.md`), how to set them up, the threat model they address, and the evidence
they produce for SOC 2, HIPAA and CIS reviews.

Code: `hopshift/services/security/` (service, store, passwords, OIDC, rate limiting, retention, posture),
`hopshift/api/routes/auth.py`, `hopshift/api/routes/users.py`, `hopshift/api/routes/audit.py`, `hopshift/api/middleware.py`, and the
`hopshift admin|secrets|audit|runs` CLI groups in `hopshift/cli/main.py`.

## What is implemented

| Area | Behaviour |
|---|---|
| Accounts | Local users with argon2id password hashes (argon2-cffi defaults: t=3, 64 MiB, p=4). Usernames are trimmed and case-insensitive. Password policy: 12-256 characters, must not contain the username. Unknown users and wrong passwords get the same `401 {"detail": "invalid username or password"}` after the same argon2 work. |
| Roles | `viewer` (read), `operator` (run mutations, approvals, plan/apply), `admin` (users, everyone's tokens, settings, audit). Enforced by `api.deps.require_role`. |
| Sessions | Cookie `hopshift_session`: a random 256-bit token, stored as sha256. Absolute expiry `security.auth.session_hours`, idle expiry `security.auth.idle_minutes` (activity is recorded at most once a minute). Flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when the request arrived over HTTPS (directly or via `X-Forwarded-Proto`). Cookie-authenticated `POST/PUT/PATCH/DELETE` requests must carry a same-origin `Origin` (or `Referer`) header (`OriginCheckMiddleware`). |
| API tokens | `Authorization: Bearer hs_...` (`hs_` + 32 url-safe random bytes). Stored as sha256; the value is shown once at creation. Each token has a role (never above the creator's role, and capped by the owner's current role), an optional expiry and a `last_used_at` (updated at most once a minute). Tokens cannot create tokens, change passwords or manage MFA. |
| MFA | TOTP (RFC 6238, 30 s, 6 digits, one step of clock drift) with 8 single-use recovery codes (stored hashed). A TOTP code is accepted once; replays inside the window are rejected. Policy `security.auth.mfa: optional` or `required`. When required, local users without MFA can only call `/api/auth/*` until they enrol; every other call returns `403 {"detail": "mfa_enrollment_required"}` and token creation is refused. SSO users are exempt (the identity provider owns MFA). TOTP secrets are stored encrypted with `HOPSHIFT_SECRET_KEY`; without a key they are stored in clear and the posture check `mfa.secrets_encrypted` fails. |
| OIDC SSO | Authorization code flow with PKCE (S256), `state` and `nonce` persisted for 10 minutes and single use, discovery and JWKS fetched over HTTPS and cached, `id_token` verified (signature, `iss`, `aud`, `exp`, `nonce`). Email domain allow-list, group-to-role mapping, user upsert. SSO accounts have no password. |
| Lockout and throttling | After `security.auth.lockout_threshold` failed logins for a username within `lockout_minutes`, further logins return `423` with `Retry-After` (also for usernames that do not exist, so the lock reveals nothing). Separately, `POST /api/auth/login` and `/api/auth/setup` are rate limited per client IP (token bucket, 20 per minute by default, `security.auth.login_rate_per_minute`) and return `429` with `Retry-After`. |
| Headers | `SecurityHeadersMiddleware`: CSP, `X-Frame-Options: DENY`, `nosniff`, referrer policy, permissions policy, COOP/CORP, `Cache-Control: no-store` on `/api`, HSTS over HTTPS. |
| Audit | Every security event goes to the hash-chained audit log with actor, IP and user agent: `auth.setup`, `auth.login` (success, failure, denied), `auth.locked`, `auth.logout`, `auth.password_changed`, `auth.mfa_enrolled`, `auth.mfa_confirmed`, `auth.mfa_disabled`, `auth.mfa_reset`, `auth.recovery_code_used`, `auth.token_created`, `auth.token_deleted`, `auth.oidc_login`, `user.created`, `user.updated`, `user.deleted`, `retention.sweep`, `secrets.rotated`. Details never contain passwords, hashes, tokens or TOTP secrets. |
| Retention | `security.retention.runs_days` and `audit_days` (0 keeps everything). An hourly background sweeper deletes old runs through the runtime (never running or paused runs) and prunes old audit entries (the chain is re-anchored and the prune itself is recorded). |
| Posture | `GET /api/settings/posture` reports pass/warn/fail checks with framework references (see below). |

Everything above is on by default: a missing `security` section means `security.auth.mode: required`.
`mode: disabled` is for local development only; every caller is then an anonymous admin and the
posture check `auth.enforced` fails.

## Setup

### First admin

Start the server and open the UI, or call the API. While no user exists, `POST /api/auth/setup`
creates the first admin and signs them in; afterwards it answers `409`.

```bash
export HOPSHIFT_SECRET_KEY="$(hopshift secrets generate-key)"   # encrypts TOTP secrets and target credentials
hopshift serve --host 127.0.0.1 --port 8080

curl -s http://127.0.0.1:8080/api/auth/status
# {"setup_required": true, "auth_mode": "required", "oidc_enabled": false, "mfa_policy": "optional", "user": null}

curl -s -c cookies.txt -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:8080' \
  -d '{"username": "admin", "password": "correct horse battery staple", "name": "Admin"}' \
  http://127.0.0.1:8080/api/auth/setup
```

The CLI can do the same without the HTTP API (useful in provisioning scripts):

```bash
hopshift admin create-user admin --role admin --name "Admin"      # prompts for the password
hopshift admin list-users
hopshift admin set-role alice operator
hopshift admin reset-password alice                                 # revokes alice's sessions
```

### Signing in and using a session

```bash
curl -s -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "correct horse battery staple"}' \
  http://127.0.0.1:8080/api/auth/login

curl -s -b cookies.txt http://127.0.0.1:8080/api/auth/me
curl -s -b cookies.txt -X POST -H 'Origin: http://127.0.0.1:8080' http://127.0.0.1:8080/api/auth/logout
```

When the account has MFA, the first call answers `401 {"detail": "mfa_required", "mfa_required": true}`;
repeat it with `"totp_code": "123456"` (or a recovery code).

### API tokens

```bash
curl -s -b cookies.txt -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:8080' \
  -d '{"name": "ci", "role": "operator", "expires_days": 90}' http://127.0.0.1:8080/api/auth/tokens
# {"id": "...", "token": "hs_...", "prefix": "hs_xxxxxxxx", "role": "operator", ...}   <- token shown once

curl -s -H 'Authorization: Bearer hs_...' http://127.0.0.1:8080/api/runs
curl -s -b cookies.txt -H 'Origin: http://127.0.0.1:8080' -X DELETE http://127.0.0.1:8080/api/auth/tokens/<id>
```

`GET /api/auth/tokens` lists your tokens (prefix, role, expiry, last use); admins see everyone's with
`?all=true`. Bearer requests are exempt from the Origin check (no ambient credential, no CSRF).

### MFA

```bash
curl -s -b cookies.txt -X POST -H 'Origin: http://127.0.0.1:8080' http://127.0.0.1:8080/api/auth/mfa/enroll
# {"secret": "BASE32...", "otpauth_uri": "otpauth://totp/hopshift:admin?secret=...&issuer=hopshift"}
# scan the URI with an authenticator app, then confirm with the current code:
curl -s -b cookies.txt -H 'Content-Type: application/json' -H 'Origin: http://127.0.0.1:8080' \
  -d '{"code": "123456"}' http://127.0.0.1:8080/api/auth/mfa/confirm
# {"recovery_codes": ["a1b2c-d3e4f", ...]}   <- 8 single-use codes, shown once; store them safely
```

`POST /api/auth/mfa/disable {password, code}` turns it off. An admin resets a lost second factor with
`POST /api/users/{id}/mfa/reset` (the user's sessions are revoked and they enrol again). Set
`security.auth.mfa: required` (also editable from Settings) to make enrolment mandatory for every
local account.

### OIDC single sign-on

```yaml
security:
  auth:
    oidc:
      enabled: true
      issuer: https://login.example.com          # must equal the `issuer` in the discovery document
      client_id: hopshift-platform
      client_secret_env: HOPSHIFT_OIDC_CLIENT_SECRET  # the secret itself lives in the environment
      scopes: [openid, profile, email, groups]
      allowed_domains: [example.com]             # empty = any verified email
      default_role: viewer
      admin_groups: [platform-admins]
      groups_claim: groups
      # redirect_uri: https://hopshift.example.com/api/auth/oidc/callback   # optional; derived from the request by default
```

Register `https://<host>/api/auth/oidc/callback` as the redirect URI at the provider. The UI's SSO
button opens `GET /api/auth/oidc/login`; after the provider redirects back, the platform exchanges
the code (with PKCE and the client secret), verifies the `id_token`, creates or updates the user
(`auth_kind: oidc`) and redirects to `/#/` with a session cookie.

Role mapping: `admin` when any value of `groups_claim` is in `admin_groups`, otherwise
`default_role`; SSO users are re-synced on each login (the last remaining admin is never demoted).
If a local account with the same username (email) already exists, it is linked only when the
provider asserts `email_verified: true`; its local role is kept. When `email` is missing from the
`id_token`, the `userinfo` endpoint is consulted.

Provider notes:

- **Okta**: issuer `https://<org>.okta.com/oauth2/default` (or a custom authorization server).
  Add a `groups` claim to the ID token (Security > API > Authorization Servers > Claims, filter
  the groups you want) and request the `groups` scope.
- **Microsoft Entra ID**: issuer `https://login.microsoftonline.com/<tenant-id>/v2.0`. Enable
  "groups" as an optional token claim (group IDs, not names) and put those IDs in `admin_groups`,
  or use app roles and set `groups_claim: roles`.
- **Google Workspace**: issuer `https://accounts.google.com`. Google does not emit groups; use
  `allowed_domains: [example.com]` with `default_role` and promote admins locally
  (`hopshift admin set-role`). The `hd` claim is not relied upon; the email domain is checked instead.

### TLS

Terminate TLS in front of the API (reverse proxy) or pass `--ssl-certfile/--ssl-keyfile` to
`hopshift serve`. Behind a proxy, forward `X-Forwarded-Proto` and `X-Forwarded-For` and keep
`--forwarded-allow-ips` restricted to the proxy addresses: the `Secure` cookie flag, HSTS and the
`transport.tls` posture check follow the forwarded scheme, and the rate limiter and audit log use
the forwarded client IP. Add the public origin to `security.allowed_origins` if the UI is served
from a different host than the API.

### Retention

```yaml
security:
  retention:
    runs_days: 90     # delete runs not updated for 90 days (running/paused runs are kept)
    audit_days: 365   # prune audit entries older than a year (the prune is itself audited)
```

Both values are editable from Settings. The sweeper runs hourly inside the server; `hopshift runs prune
--older-than-days N [--dry-run]` runs the run part on demand and records a `retention.sweep` entry.

### Key rotation

`HOPSHIFT_SECRET_KEY` holds one or more comma-separated Fernet keys; the first encrypts, all decrypt.

```bash
NEW="$(hopshift secrets generate-key)"
export HOPSHIFT_SECRET_KEY="$NEW,$OLD"
hopshift secrets rotate          # re-encrypts TOTP secrets (and connection credentials when that service is present)
export HOPSHIFT_SECRET_KEY="$NEW" # drop the old key once the rotation printed the row counts
```

If secrets were stored before a key existed (posture `mfa.secrets_encrypted` fails), setting the key
and running `hopshift secrets rotate` encrypts them in place.

### Audit log

`GET /api/audit?limit&offset&action&actor&since&target_id&target_type&outcome` (admin) pages the
log newest first; `GET /api/audit/verify` recomputes the chain; `GET /api/audit/export` streams every
entry as NDJSON for evidence collection. `hopshift audit verify` does the same from the shell and exits
non-zero when the chain is broken.

## Threat model

| Threat | Control |
|---|---|
| Credential stuffing, password spraying | argon2id hashing, 12-character minimum, per-username lockout (`423`), per-IP throttling (`429`), identical responses for unknown users and wrong passwords, every failure audited with actor and IP. |
| Session theft (XSS, network) | Random 256-bit tokens stored hashed, `HttpOnly` cookie, `Secure` over TLS, strict CSP, absolute and idle expiry, revocation on logout, password change (other sessions), disable, delete and MFA reset. |
| CSRF | `SameSite=Lax` plus an Origin/Referer check on every cookie-authenticated mutation; bearer tokens carry no ambient credential. |
| Leaked API token | Stored hashed, shown once, optional expiry, `last_used_at` for review, role capped at creation and by the owner's current role, revocable by owner or admin, revoked when the owner is disabled. |
| Stolen password | Optional or mandatory TOTP MFA, single-use codes (no replay), single-use hashed recovery codes, admin reset path. |
| Compromised identity-provider redirect | PKCE (S256), server-stored single-use `state`, `nonce` bound to the `id_token`, signature and `iss`/`aud`/`exp` verification against the provider's JWKS, domain allow-list, verified-email requirement for linking. |
| Privilege escalation | Role hierarchy enforced in `require_role`; tokens cannot exceed or outlive their owner's role; the last admin cannot be demoted, disabled or deleted; nobody can delete or disable themselves; tokens cannot mint tokens or change passwords. |
| Account enumeration | Same 401 for unknown and known users; lockout counted per submitted username regardless of existence; OIDC errors are generic. |
| Database read by an attacker | Passwords (argon2id), sessions, tokens and recovery codes are hashes; TOTP secrets are Fernet-encrypted with a key kept outside the database; `encrypt_run_inputs` protects inventory data the same way. |
| Log tampering | Hash-chained audit entries; `verify` finds the first altered or deleted row; pruning re-anchors and records itself. |
| Clickjacking, MIME sniffing, referrer leaks | `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`. |

Out of scope: physical access to the host, compromise of the identity provider itself, and
protection of the `HOPSHIFT_SECRET_KEY` environment variable (use the orchestrator's secret store).

## Compliance evidence

The posture endpoint (`GET /api/settings/posture`) returns these checks with their framework
references; each is `pass`, `warn` or `fail` and carries a human-readable detail.

| Check | Evidence for |
|---|---|
| `auth.enforced` | SOC 2 CC6.1, HIPAA 164.312(d), CIS 6.3 |
| `secrets.key` | SOC 2 CC6.1, HIPAA 164.312(a)(2)(iv) |
| `audit.chain` | SOC 2 CC7.2, HIPAA 164.312(b), CIS 8.2 |
| `transport.tls` | SOC 2 CC6.7, HIPAA 164.312(e)(1), CIS 3.10 |
| `retention.runs`, `retention.audit` | SOC 2 CC6.5 / CC7.2, HIPAA 164.310(d)(2)(i) / 164.316(b)(2)(i), CIS 8.10 |
| `mfa.policy`, `mfa.coverage`, `mfa.secrets_encrypted` | SOC 2 CC6.1, HIPAA 164.312(d) / 164.312(a)(2)(iv), CIS 6.5 |
| `oidc.configured` | SOC 2 CC6.1, CIS 6.7 (centralised identity) |
| `api.docs` | CIS 4.8, SOC 2 CC6.6 (attack surface) |
| `session.lifetime` | SOC 2 CC6.1, HIPAA 164.312(a)(2)(iii) (automatic logoff), CIS 4.3 |
| `auth.lockout` | SOC 2 CC6.1, CIS 6.2 |
| `runs.encrypt_inputs` | HIPAA 164.312(a)(2)(iv), SOC 2 CC6.1, CIS 3.11 |
| `deploy.allow_destroy` | SOC 2 CC8.1 (change management), CIS 4.1 |

Further evidence auditors typically ask for and where it comes from:

- **Access reviews** (SOC 2 CC6.2/CC6.3, HIPAA 164.308(a)(3)): `GET /api/users`, `GET /api/auth/tokens?all=true`,
  `hopshift admin list-users` (roles, MFA state, last login, disabled accounts).
- **Authentication events** (SOC 2 CC6.1, HIPAA 164.312(b), CIS 8.5): `auth.*` audit entries with actor, IP and user agent.
- **Change history** (SOC 2 CC8.1): `user.*`, `settings.updated`, `run.*` and deployment entries in the same chain.
- **Integrity of the evidence** (SOC 2 CC7.2): `GET /api/audit/verify`, `hopshift audit verify`, NDJSON export.
- **Data disposal** (HIPAA 164.310(d)(2)(i)): `retention.sweep` entries list how many runs and audit rows were removed.
- **Key management** (HIPAA 164.312(a)(2)(iv)): `secrets.rotated` entries with the primary key fingerprint.

None of this is a certification; it is the technical control set and the records an assessor needs.
