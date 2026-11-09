# CLI Reference

CLI entrypoint is cli/main.py.

## Command: terragen

Converts VMware discovery JSON into provider HCL via the full pipeline.

Required options:

- --input
- --cloud (aws|azure|gcp|openstack)
- --environment
- --owner

Mode:

- --mode (deterministic|llm|hybrid); defaults to generation.mode in config.yaml (deterministic).
- --llm-provider (anthropic|openai|google) is required for llm and hybrid modes and optional otherwise (used for review notes when set).

Optional options:

- --llm-model
- --llm-base-url (or env var LLM_BASE_URL)
- --llm-api-key (or env var LLM_API_KEY)
- --output-dir (default: output)
- --config (default: config.yaml)

Flags:

- --dry-run (runs the full pipeline, including validation, but writes no files)
- --skip-validation (disables terraform validate, tflint, OPA)
- --skip-opa
- --no-mcp (disables Terraform MCP documentation retrieval; no docker required)

Exit status:

- 0 when the final status is succeeded
- 1 otherwise; the first validation errors are printed to stderr

Example:

```bash
vma terragen --input discovery.json --cloud aws --llm-provider anthropic --environment prod --owner platform-team
```

## Command: assess

Runs the deterministic risk assessment over the whole inventory (blocked VMs are assessed, not quarantined) and writes assessment_report.json and assessment_report.md plus a terminal table. No LLM, no cloud access, no docker.

```bash
vma assess --input discovery.json --cloud aws --output-dir output
```

## Command: serve

Starts the platform: the HTTP API under `/api`, Swagger UI at `/docs` and the built web UI at `/`.

```bash
export VMA_SECRET_KEY=$(vma secrets generate-key)
vma serve --host 0.0.0.0 --port 8080
vma serve --ssl-certfile cert.pem --ssl-keyfile key.pem           # direct TLS
vma serve --forwarded-allow-ips 10.0.0.5                           # behind a reverse proxy
```

Options: `--config`, `--host` (default 127.0.0.1), `--port` (default 8080), `--ssl-certfile`,
`--ssl-keyfile`, `--forwarded-allow-ips` (proxies whose `X-Forwarded-*` headers are trusted,
default 127.0.0.1). The first visit shows the setup screen while no user exists.

## Command group: admin

Local accounts (`security.auth.mode: required`). Works before first-run setup, so it can
bootstrap the first administrator on a headless server.

```bash
vma admin create-user admin --role admin --name "Platform admin"   # prompts for the password
vma admin list-users
vma admin reset-password alice                                      # revokes her sessions
vma admin set-role alice operator                                   # the last admin cannot be demoted
```

Options: `--config` (default config.yaml); `create-user` also takes `--password` (prompted
when omitted so it stays out of shell history).

## Command group: secrets

```bash
vma secrets generate-key          # print a new Fernet key for VMA_SECRET_KEY
VMA_SECRET_KEY=<new>,<old> vma secrets rotate   # re-encrypt every stored secret with <new>, then drop <old>
```

`rotate` reports the number of rows rewritten per service (credentials, MFA secrets, device
flows) and records `secrets.rotated` in the audit log.

## Command: audit verify

Recomputes the audit log hash chain and exits non-zero when an entry was altered or removed.

## Command: runs prune

```bash
vma runs prune --older-than-days 30 --dry-run
vma runs prune --older-than-days 30
```

Deletes runs through the runtime (never running or paused ones) and audits the sweep. The
API's hourly sweeper does the same when `security.retention.runs_days` is set.

## Command: report

Reads existing artifacts from an output directory.

Arguments/options:

- output_dir (required argument)
- --format (text|json)

Expected files:

- review_notes.md
- quarantine_report.json

Example:

```bash
vma report output --format text
```

## Command: mcp-check

Validates Terraform MCP stdio connectivity.

Options:

- --config (default: config.yaml)
- --servers (comma-separated names or configured)
- --top-k
- --timeout
- --format (text|json)

Example:

```bash
vma mcp-check --servers terraform --timeout 10 --format text
```

## Runtime Overrides Applied By CLI

Before graph execution, terragen injects overrides into runtime config:

- target_cloud from --cloud.
- llm.provider and llm.model from CLI values.
- llm.base_url when provided.
- output.base_dir from --output-dir; output.dry_run from --dry-run.
- mcp.enabled=false from --no-mcp.
- validation skip flags from --skip-validation and --skip-opa.
- required_tags.Environment and required_tags.Owner from CLI.
