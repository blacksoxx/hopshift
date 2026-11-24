# CLI Reference

The entry point is the `hopshift` console script (`hopshift/cli/main.py`); `python -m hopshift.cli.main` is equivalent and is what the container uses.

## Command: terragen

Runs the full pipeline from a discovery JSON to a Terraform root module for one target.

Required options:

- --input
- --cloud: a registered target name (`aws`, `azure`, `gcp`, `openstack`, `proxmox` built in; plugins add their own; `--help` lists them)
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
hopshift terragen --input discovery.json --cloud aws --llm-provider anthropic --environment prod --owner platform-team
```

## Command: assess

Runs the deterministic risk assessment over the whole inventory (blocked VMs are assessed, not quarantined) and writes assessment_report.json and assessment_report.md plus a terminal table. No LLM, no cloud access, no docker.

```bash
hopshift assess --input discovery.json --cloud aws --output-dir output
```

## Command: serve

Starts the platform: the HTTP API under `/api`, Swagger UI at `/docs` and the built web UI at `/`.

```bash
export HOPSHIFT_SECRET_KEY=$(hopshift secrets generate-key)
hopshift serve --host 0.0.0.0 --port 8080
hopshift serve --ssl-certfile cert.pem --ssl-keyfile key.pem           # direct TLS
hopshift serve --forwarded-allow-ips 10.0.0.5                           # behind a reverse proxy
```

Options: `--config`, `--host` (default 127.0.0.1), `--port` (default 8080), `--ssl-certfile`,
`--ssl-keyfile`, `--forwarded-allow-ips` (proxies whose `X-Forwarded-*` headers are trusted,
default 127.0.0.1). The first visit shows the setup screen while no user exists.

## Command group: admin

Local accounts (`security.auth.mode: required`). Works before first-run setup, so it can
bootstrap the first administrator on a headless server.

```bash
hopshift admin create-user admin --role admin --name "Platform admin"   # prompts for the password
hopshift admin list-users
hopshift admin reset-password alice                                      # revokes her sessions
hopshift admin set-role alice operator                                   # the last admin cannot be demoted
```

Options: `--config` (default config.yaml); `create-user` also takes `--password` (prompted
when omitted so it stays out of shell history).

## Command group: secrets

```bash
hopshift secrets generate-key          # print a new Fernet key for HOPSHIFT_SECRET_KEY
HOPSHIFT_SECRET_KEY=<new>,<old> hopshift secrets rotate   # re-encrypt every stored secret with <new>, then drop <old>
```

`rotate` reports the number of rows rewritten per service (credentials, MFA secrets, device
flows) and records `secrets.rotated` in the audit log.

## Command: audit verify

Recomputes the audit log hash chain and exits non-zero when an entry was altered or removed.

## Command: runs prune

```bash
hopshift runs prune --older-than-days 30 --dry-run
hopshift runs prune --older-than-days 30
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
hopshift report output --format text
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
hopshift mcp-check --servers terraform --timeout 10 --format text
```

## Command groups: targets, sources, plugins, matrix

Registry and conformance commands (see [plugins.md](plugins.md) and [support-matrix.md](support-matrix.md)).

```bash
hopshift targets list [--format json]               # registered targets with tier, tflint, connection, package
hopshift targets check aws [--terraform] [--input discovery.json] [--format json]
hopshift sources list
hopshift sources check vmware --input tests/fixtures/discovery_multi_vm.json
hopshift plugins list                               # entry points and their load status (exit 1 if one is broken)
hopshift matrix render [--support support.yaml] [--output docs/support-matrix.md]
hopshift matrix check                               # exit 1 when support.yaml is invalid or the doc is stale
```

`check` runs the conformance kit (renderer contract, layout, guards, parse, determinism, OPA)
and exits 1 on any failure; `--terraform` adds `terraform init` and `validate`, plus `tflint`
when the target declares a ruleset.

## Runtime Overrides Applied By CLI

Before graph execution, terragen injects overrides into runtime config:

- target_cloud from --cloud (validated against the target registry).
- llm.provider and llm.model from CLI values.
- llm.base_url when provided.
- output.base_dir from --output-dir; output.dry_run from --dry-run.
- mcp.enabled=false from --no-mcp.
- validation skip flags from --skip-validation and --skip-opa.
- required_tags.Environment and required_tags.Owner from CLI.
