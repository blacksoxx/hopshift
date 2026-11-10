# Deployments

The platform can run Terraform against the root module a run generated: `plan`, then `apply`
with an explicit approval, and later `destroy`. The executor lives in `vma/deploy/`; the HTTP
surface is `api/routes/deploy.py`. Nothing here touches the pipeline: a deployment is a
separate, audited action on a run that already succeeded.

## Lifecycle

```
run succeeded ──▶ plan ──▶ (review plan.json / log) ──▶ apply (plan_id + confirmation) ──▶ destroy (confirmation)
                   │                                      │
                   └── failed / cancelled                  └── failed / cancelled
```

A deployment record moves through `queued → running → succeeded | failed | cancelled`. Only one
deployment per run can be queued or running at a time (a second request gets `409`), and a run
with an active deployment cannot be deleted.

Each action runs these commands in the workspace (all with `-no-color -input=false`):

| action | commands | success |
|---|---|---|
| `plan` | `init -reconfigure`, `plan -detailed-exitcode -out=tfplan`, `show -json tfplan` | exit code 0 (no changes) or 2 (changes); 1 is a failure |
| `apply` | `init -reconfigure`, `apply <tfplan copied from the plan>` | exit code 0 |
| `destroy` | `init -reconfigure`, `destroy -auto-approve` | exit code 0 |

The `summary` on a record is `{add, change, destroy, replace, resources: [{address, type, actions}]}`.
For a plan it comes from `plan.json` (a replacement counts once under `replace`, not as an add
plus a destroy); for apply and destroy it comes from Terraform's final `Apply complete!` /
`Destroy complete!` line, with the resource list carried over from the plan.

## Gates

| action | requirements |
|---|---|
| any | the run exists, its status is `succeeded`, and `artifacts/<cloud>-migration/` contains `.tf` files; a `connection_id` when the connections service is available |
| `plan` | nothing more |
| `apply` | `deploy.allow_apply` is on; `plan_id` names a **succeeded plan of the same run that found changes**, and the generated `.tf` files have not changed since (a sha256 over their sorted paths and contents is recorded on the plan); `confirmation` equals the run id |
| `destroy` | `deploy.allow_destroy` is on; `confirmation` equals the run id |

A failed gate is refused with `400` (invalid or stale request) or `403` (flag off, bad
confirmation) and recorded in the audit log as `deployment.denied`. The operator who passes the
confirmation becomes `approved_by` on the record. `deploy.allow_apply`, `deploy.allow_destroy`
and `deploy.timeout_minutes` are editable from Settings by an admin.

Roles: `viewer` can read deployments, logs, plans, variables and state; `operator` can request
plan / apply / destroy, cancel, and set variables.

## Where things live

```
output/runs/<run_id>/
  artifacts/<cloud>-migration/      the generated root module (never modified by a deployment)
  deploy/
    workspace/                      fresh copy of the root module made at the start of every deployment
    state/terraform.tfstate         local backend state (kept out of artifacts/)
    .terraform/                     TF_DATA_DIR: providers and modules
    terraform.lock.hcl              provider lock carried from one deployment to the next
    terraform.tfvars.json           variable values set through the API
    <deployment_id>/
      deployment.json               mirror of the SQLite row
      terraform.log                 streamed, masked output of every command
      tfplan                        the saved plan (plan deployments)
      plan.json                     `terraform show -json` output (plan deployments)
output/platform.sqlite              `deployments` table used for listing and the active check
```

The workspace gets a `backend_override.tf` (Terraform merges `*_override.tf` files over
`providers.tf`), so the generated files stay valid on their own and the backend is decided by the
platform. Provider downloads go through `validation.terraform_plugin_cache_dir` when it is set.

### Environment given to Terraform

- the API process environment **minus** every `AWS_*`, `ARM_*`, `GOOGLE_*` and `OS_*` variable,
- plus the connection's `terraform_env` (credentials resolved by the connections service),
- plus `TF_DATA_DIR`, `TF_IN_AUTOMATION=1`, `TF_INPUT=0` and `TF_PLUGIN_CACHE_DIR`.

When the connections service is not installed (`platform.connections is None`, for example a
CLI-only setup), `connection_id` may be omitted and Terraform inherits the process environment
unchanged: whatever `AWS_PROFILE`, `ARM_CLIENT_ID`, ... the server was started with. This is meant
for local use only; with the connections service present a connection is mandatory.

### Logs and masking

Output is streamed line by line into `terraform.log` and exposed through `GET .../log?since=N`
(returns `{lines, next, done}`) and `GET .../log/stream` (server-sent events: one `data:` event
per line as `{"index", "line"}`, a `: keep-alive` comment every ~4 s of silence, and
`event: done` with the final status). Before a line is written:

1. every secret value the connections service reports for the connection (and the values of
   secret-looking variables in `terraform_env`) is replaced by `***`,
2. any `key = value` / `key: value` whose key contains `secret`, `password` or `token` has its
   value replaced by `***`.

`plan.json` has the values of variables declared `sensitive = true` blanked and literal secret
values masked. Nothing else in the plan is altered, so review it as you would a plan file.

### Timeout and cancel

`deploy.timeout_minutes` bounds the whole deployment. When it elapses the Terraform process group
is killed and the record ends `failed` with a timeout error. `POST .../cancel` sends `SIGTERM` to
the process group, then `SIGKILL` after 10 s; the record ends `cancelled`. A platform restart
marks any deployment still `queued` or `running` as `failed` (interrupted), since its process is gone.

## Variables

`GET /runs/{id}/deploy/variables` parses `variables.tf` of the root module and returns, per
variable, `{name, type, description, default, sensitive, required, set, value}`; `value` is the
current entry from `terraform.tfvars.json` (masked when the variable is sensitive).
`PUT /runs/{id}/deploy/variables {"values": {...}}` validates names and basic types
(`string`, `number`, `bool`, `list(...)`, `map(...)`), writes `terraform.tfvars.json`, and is
audited as `variables.updated` (names only). A `null` value removes an entry.

Variables that matter for every AWS run: `aws_region`, `default_availability_zone`,
`default_ami_id` (fallback AMI) and `image_overrides` (AMI per VMware VM name produced by VM
Import/Export). A plan embeds the variable values it was made with; `apply` reuses the plan file,
so changing variables between plan and apply has no effect until the next plan.

## State

By default state is local, in `deploy/state/terraform.tfstate`, and `GET /runs/{id}/deploy/state`
summarises it: `{exists, serial, terraform_version, lineage, resources: [{address, type}]}`.

### Remote state

```yaml
deploy:
  remote_state:
    enabled: true
    type: s3            # s3 | azurerm | gcs
    config:
      bucket: my-tf-state
      key: vma/runs.tfstate
      region: us-east-1
      encrypt: true
```

`config` is rendered as backend attributes (strings quoted, booleans and numbers bare), with one
addition: the platform namespaces the state per run so two runs can never share a state file.
For `s3` and `azurerm` the `key` you configure becomes a prefix (`<key>/<run_id>/terraform.tfstate`);
for `gcs` the `prefix` becomes `<prefix>/<run_id>`. Enable locking: `use_lockfile: true` on `s3`
(Terraform 1.10+, no DynamoDB table needed; `dynamodb_table` still works), `azurerm` and `gcs`
lock natively. Use the connection's credentials for the backend too: Terraform's `s3`, `azurerm`
and `gcs` backends read the same `AWS_*` / `ARM_*` / `GOOGLE_*` variables as the providers. With
remote state enabled the state endpoint reports `{exists: false, remote: true, backend: "<type>"}`; inspect it
with `terraform state list` in the workspace.

## LocalStack: a real AWS plan and apply without an account

LocalStack emulates the AWS APIs locally, which is enough to exercise init, plan and apply on a
generated module end to end.

1. Start LocalStack (the free image covers EC2, VPC and EBS):

   ```bash
   docker run --rm -d --name localstack -p 4566:4566 localstack/localstack
   ```

   If the platform itself runs in Docker (see `docker-compose.yml`), put LocalStack on the same
   network and refer to it as `http://localstack:4566`; from the host use `http://localhost:4566`.

2. Create an AWS connection with the `access_keys` method: key id `test`, secret `test`,
   region `us-east-1`, and `endpoint_url` `http://localstack:4566` (or `http://localhost:4566`).
   The connections service turns the endpoint into the provider's environment
   (`AWS_ENDPOINT_URL`, which Terraform's AWS provider 5.x+ honours for every service).

3. The generated `providers.tf` needs three settings the real AWS API does not, otherwise the
   provider tries to call STS and validate the region against the public endpoints. Add a
   `provider_override.tf` in the run's root module (`artifacts/aws-migration/`) with:

   ```hcl
   provider "aws" {
     region                      = var.aws_region
     skip_credentials_validation = true
     skip_requesting_account_id  = true
     skip_metadata_api_check     = true
     s3_use_path_style           = true
   }
   ```

   Override files are merged into the generated provider block, so the module stays unchanged
   otherwise. Remember that editing the root module after a plan invalidates that plan (the
   apply gate recomputes the artifacts hash).

4. Set `default_ami_id` to any `ami-` id (LocalStack accepts arbitrary ids), run `plan`,
   review `plan.json`, then `apply` with `plan_id` and `confirmation`. `GET .../deploy/state`
   lists the created resources; `destroy` removes them.

LocalStack does not implement placement groups or every EBS option identically to AWS; a
resource LocalStack rejects shows up as an apply error in `terraform.log` and is not a defect of
the generated HCL.

## API summary

```
GET  /api/runs/{id}/deployments                           list (newest first)
POST /api/runs/{id}/deployments                           {action, connection_id?, plan_id?, confirmation?} -> 202, queued record
GET  /api/runs/{id}/deployments/{dep_id}                  record
GET  /api/runs/{id}/deployments/{dep_id}/log?since=N      {lines, next, done}
GET  /api/runs/{id}/deployments/{dep_id}/log/stream       server-sent events
GET  /api/runs/{id}/deployments/{dep_id}/plan             plan.json (plan deployments only)
POST /api/runs/{id}/deployments/{dep_id}/cancel           -> 202 with the record
GET  /api/runs/{id}/deploy/variables                      parsed variables.tf merged with tfvars
PUT  /api/runs/{id}/deploy/variables                      {values}
GET  /api/runs/{id}/deploy/state                          local state summary
```

A typical sequence with `curl` (session cookie or `Authorization: Bearer hs_...` as usual):

```bash
RUN=20261108T142203Z-4ab07013
curl -s -X PUT localhost:8000/api/runs/$RUN/deploy/variables \
  -H 'content-type: application/json' -d '{"values": {"aws_region": "us-east-1", "default_ami_id": "ami-0123456789abcdef0"}}'
PLAN=$(curl -s -X POST localhost:8000/api/runs/$RUN/deployments \
  -H 'content-type: application/json' -d '{"action": "plan", "connection_id": "<connection id>"}' | jq -r .id)
curl -sN localhost:8000/api/runs/$RUN/deployments/$PLAN/log/stream      # until "event: done"
curl -s localhost:8000/api/runs/$RUN/deployments/$PLAN | jq .summary
curl -s -X POST localhost:8000/api/runs/$RUN/deployments \
  -H 'content-type: application/json' \
  -d "{\"action\": \"apply\", \"connection_id\": \"<connection id>\", \"plan_id\": \"$PLAN\", \"confirmation\": \"$RUN\"}"
```

Audit events: `deployment.requested`, `deployment.finished` (status, exit code, counts),
`deployment.cancelled`, `deployment.denied`, `variables.updated`. Details never include values.

## Troubleshooting

| symptom | cause and fix |
|---|---|
| `503 terraform binary not found` | `deploy.terraform_bin` is not on the API's `PATH` (in Docker the image ships it; locally install Terraform ≥ 1.5). |
| `400 connection_id is required` | The connections service is installed, so every deployment needs a connection; create one and pass its id. |
| `400 connection ... is for azure, the run targets aws` | Pick a connection whose provider matches the run's cloud. |
| `init` fails with provider download errors | No network to the registry: pre-populate `validation.terraform_plugin_cache_dir` or mount a filesystem mirror. |
| `plan` fails with `no valid credential sources` | The connection's `terraform_env` produced nothing usable (expired SSO/assume-role, missing secret because `HOPSHIFT_SECRET_KEY` changed). Test the connection first. |
| `400 the generated Terraform changed since plan ...` | The artifacts were regenerated or edited after the plan; run `plan` again. |
| `400 plan ... found no changes; nothing to apply` | The plan exited 0; there is nothing to apply. |
| `409 already has an active deployment` | Wait for it or cancel it; the UI shows the running record. |
| record `failed`, error `interrupted` | The API restarted while Terraform ran; check the cloud console or the state, then plan again. |
| status `failed` with `timed out` | Raise `deploy.timeout_minutes` (Settings) or split the estate. |
| state summary is `{exists: false}` after an apply | Remote state is enabled, or the apply did not reach the point of writing state; see `terraform.log`. |
| secrets visible in a log | The connections service must report the value through `secret_values(connection_id)`; the regex fallback only catches `secret|password|token` keys. Report it as a bug. |
