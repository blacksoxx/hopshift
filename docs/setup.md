# Setup and operations

How to install, run, secure and operate the platform: locally for development, with Docker
for a team, and behind TLS for production.

## 1. Requirements

| Component | Version | Needed for |
|---|---|---|
| Python | 3.12 | everything |
| Node.js | 22 | building the UI (not needed with Docker) |
| terraform | 1.17.x | validation and deployments |
| tflint | 0.66.x | validation |
| opa | 1.22.x | security and compliance policies |
| Docker | any recent | the container stack; the Terraform MCP docs server (optional) |

The container image ships all of these pinned; the versions are build arguments in the
Dockerfile.

## 2. Quick start with Docker (recommended)

```bash
git clone https://github.com/blacksoxx/hopshift.git
cd hopshift
cp .env.example .env
# generate the key that encrypts stored credentials and put it in .env as HOPSHIFT_SECRET_KEY
docker compose run --rm --no-deps agent python -m hopshift.cli.main secrets generate-key
docker compose up -d --build
```

Open http://localhost:8080 (change the host port with `HOPSHIFT_PORT=8088` in `.env`). The first
visit shows the setup screen to create the administrator account. Runs, the platform database
and generated Terraform persist under `./output`; the Terraform provider cache persists in the
`agent-home` volume.

The container runs as a non-root user with a read-only root filesystem, no new privileges and
all capabilities dropped. To use cloud CLI profiles from the host (the `profile`, `cli`, `adc`
and `clouds_yaml` connection methods), uncomment the matching volume lines in
`docker-compose.yml`.

## 3. Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
(cd ui && npm ci && npm run build)       # or `npm run dev` for hot reload on :5173
export HOPSHIFT_SECRET_KEY=$(hopshift secrets generate-key)
hopshift serve                                 # http://127.0.0.1:8080
```

`hopshift serve` serves the API under `/api`, Swagger UI at `/docs` and the built UI at `/`.
Useful flags: `--host`, `--port`, `--config`, `--ssl-certfile/--ssl-keyfile`,
`--forwarded-allow-ips` (proxies whose `X-Forwarded-*` headers are trusted).

For a development instance without accounts set `security.auth.mode: disabled` in a copy of
`config.yaml` and pass it with `--config`. Never do this on a shared network.

## 4. Configuration

Everything lives in `config.yaml`; sections are documented inline and in
[configuration.md](configuration.md). The parts that matter for operations:

- `security.auth`: `mode` (required/disabled), session and idle lifetimes, MFA policy
  (`optional`/`required`), lockout, OIDC provider settings.
- `security.secret_key_env`: the environment variable holding the Fernet key(s), default
  `HOPSHIFT_SECRET_KEY`.
- `security.headers`, `security.allowed_origins`, `security.api_docs`.
- `security.retention`: delete runs and prune audit entries older than N days (0 keeps all).
- `security.encrypt_run_inputs`: store `discovery.json` encrypted.
- `runtime`: run folder, checkpoint database, platform database, default pause points.
- `deploy`: terraform binary, timeout, `allow_apply`, `allow_destroy`, remote state backend.
- `validation`: terraform/tflint/opa switches, plugin cache directory.
- `llm`, `generation`, `output`: model and generation behaviour.

A small set of these can be changed from the UI by an administrator (Settings → General); the
overrides live in the platform database and are audited.

Environment variables (see `.env.example`): `HOPSHIFT_SECRET_KEY`, `HOPSHIFT_OIDC_CLIENT_SECRET`,
`HOPSHIFT_PORT`, and the optional model provider keys.

## 5. First administrator, users, tokens

- UI: the setup screen appears while no user exists.
- CLI: `hopshift admin create-user --username admin --role admin` (prompts for the password),
  `hopshift admin reset-password`, `hopshift admin list-users`, `hopshift admin set-role`.
- API tokens for automation: Settings → Tokens, or `POST /api/tokens`. Send them as
  `Authorization: Bearer hs_...`. A token never has more rights than the user who created it.
- Roles: `viewer` reads, `operator` runs and approves, `admin` manages users, connections and
  settings and reads the audit log.

Enable the second factor under Profile & security; set `security.auth.mfa: required` to make
it mandatory for everyone. See [security.md](security.md) for OIDC single sign-on.

## 6. Production checklist

1. **TLS.** Terminate TLS in front of the API (nginx, Caddy, a cloud load balancer) and pass
   `X-Forwarded-Proto`; start `hopshift serve --forwarded-allow-ips <proxy-ip>`. Or give uvicorn the
   certificate directly with `--ssl-certfile/--ssl-keyfile`. HSTS and `upgrade-insecure-requests`
   are emitted only on HTTPS.
2. **Secrets.** Generate `HOPSHIFT_SECRET_KEY` once, store it in your secret manager, back it up
   with the database. Rotate with `hopshift secrets rotate` after adding a new key in front of the
   old one (comma-separated).
3. **Accounts.** Keep `security.auth.mode: required`, consider `mfa: required`, configure OIDC
   for your identity provider, give operators the smallest role that works.
4. **Retention.** Set `security.retention.runs_days` and `audit_days` to match your policy.
5. **Backups.** Back up `output/` (runs, `platform.sqlite`, checkpoints, Terraform state) and
   the key. Restore is copying the folder back.
6. **Network.** Expose only the API port; the container needs outbound access to the cloud APIs,
   the Terraform registry (provider downloads) and, if used, the model provider.
7. **Posture.** Settings → Posture shows live checks (auth, MFA, TLS, key, audit chain,
   retention, docs exposure, destroy allowed) mapped to SOC 2, HIPAA and CIS references.

## 7. Operations

- Logs: structured console logs (`logging.format: json` for log shippers) plus the detailed log
  file under `output/`.
- Health: `GET /api/health`; the container's HEALTHCHECK uses it.
- Audit: Settings → Audit, `GET /api/audit`, `hopshift audit verify` to check the hash chain,
  `GET /api/audit/export` for ndjson.
- Prune: `hopshift runs prune --older-than-days 30 --dry-run`.
- Upgrade: pull the new image or code, restart; migrations apply automatically at start.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Setup screen never appears / 404 on `/api/auth/status` | Running an old build without the security module; rebuild the image or reinstall. |
| "no encryption key configured" when saving a connection | `HOPSHIFT_SECRET_KEY` is not set in the server's environment. |
| Validation fails with provider download errors | No outbound access to the Terraform registry, or the plugin cache directory is not writable. |
| `plan` fails at provider configuration | The connection's credentials are wrong or expired; use Test on the connection page. |
| Browser shows a blank page behind a proxy | The proxy strips `X-Forwarded-Proto`, so the CSP `upgrade-insecure-requests` directive is missing or present wrongly; pass the header and set `--forwarded-allow-ips`. |
| Login returns 429 | Per-IP throttling after too many attempts; wait for `Retry-After`. |
