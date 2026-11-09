# Cloud Connections

A connection stores how the platform authenticates to a cloud account: the provider, an auth
method from the catalog, non-secret configuration, and (encrypted) secrets. Runs reference a
connection, `terraform plan/apply` receives its credentials as environment variables, and the
**Test** action verifies the identity against the cloud without touching any resources.

Code: `vma/connections/` (service, catalog, provider modules) and `api/routes/connections.py`.

## Record

| field | description |
|---|---|
| `id` | uuid4 hex |
| `name` | unique (case-insensitive), 1 to 80 characters |
| `provider` | `aws`, `azure`, `gcp` or `openstack` |
| `auth_method` | a method key from the catalog below |
| `config` | the non-secret fields of the method |
| `status` | `unverified` after create or update, `ok` or `failed` after a test |
| `last_checked_at`, `last_check` | time and `{identity, message}` of the last test |
| `has_secret`, `secret_fields` | whether secrets are stored and the names of the stored fields (API only) |
| `terraform_ready` | whether `terraform_env` can resolve credentials for this method |
| `created_by`, `created_at`, `updated_at` | audit metadata |

## API

All paths under `/api`; roles as in `docs/platform-plan.md`.

```
GET    /connections/methods                 catalog (viewer)
GET    /connections[?provider=aws]          list (viewer)
GET    /connections/{id}                    one connection (viewer)
POST   /connections                         {name, provider, auth_method, config, secret} (admin) -> 201
PATCH  /connections/{id}                    {name?, config?, secret?} partial update (admin)
DELETE /connections/{id}                    (admin) -> 204
POST   /connections/{id}/test               {ok, identity, message, checked_at} (operator)
POST   /connections/{id}/device/start       {flow_id, user_code, verification_uri, verification_uri_complete, expires_in, interval} (operator)
POST   /connections/{id}/device/poll        {flow_id} -> {status: pending|complete|expired|error, message} (operator)
```

`config` and `secret` are validated against the catalog: unknown fields are rejected, required
fields must be present, secret fields must be sent in `secret` (never in `config`), select
fields must use a listed option. `PATCH` merges `config` and `secret` onto the stored values; a
key set to `null` removes it. Any change to `config` or `secret` resets `status` to
`unverified`; a rename alone keeps it.

Errors: 400 for validation problems, 404 for unknown connections or flows, 409 for duplicate
names, 503 when secrets cannot be stored because no encryption key is configured.

Example: create and test an AWS access-keys connection.

```bash
curl -s -X POST http://localhost:8080/api/connections \
  -H 'Content-Type: application/json' \
  -d '{"name": "lab", "provider": "aws", "auth_method": "access_keys",
       "config": {"access_key_id": "AKIA...", "region": "eu-west-1"},
       "secret": {"secret_access_key": "..."}}'
# -> {"id": "<id>", "status": "unverified", "has_secret": true, "secret_fields": ["secret_access_key"], ...}

curl -s -X POST http://localhost:8080/api/connections/<id>/test
# -> {"ok": true, "identity": {"account": "123456789012", "arn": "arn:aws:iam::123456789012:user/...", "user_id": "...", "region": "eu-west-1"}, ...}
```

## Catalog

`GET /connections/methods` returns, per provider, the methods and their fields:
`{key, label, type, required, secret, help, options?, placeholder?, default?}` with `type` one
of `text`, `password`, `textarea`, `select`, `boolean`, `number`. `secret: true` fields are
stored encrypted and never returned. The UI renders forms from this description.

### AWS

Common to every method: `region` (required; `AWS_REGION` and `AWS_DEFAULT_REGION`) and
`endpoint_url` (optional; `AWS_ENDPOINT_URL`, see LocalStack below).

| method | fields | verifies | Terraform environment |
|---|---|---|---|
| `access_keys` | `access_key_id`, `secret_access_key` (secret), `session_token` (secret, optional) | STS `GetCallerIdentity` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` |
| `profile` | `profile`, `shared_credentials_file` (optional), `config_file` (optional) | STS with the named profile | `AWS_PROFILE`, `AWS_SDK_LOAD_CONFIG=1`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE` |
| `assume_role` | `base_method` (`access_keys`, `profile` or `environment`) plus that method's fields, `role_arn`, `external_id` (optional), `session_name` (default `vmware-migration-agent`) | STS `AssumeRole` then `GetCallerIdentity` | temporary `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` from the assumed role |
| `environment` | none | STS with whatever the process has (env vars, instance role, ECS task role, IRSA) | region only |
| `sso` | `start_url`, `sso_region`, `account_id`, `role_name` | after the device flow: `sso.GetRoleCredentials` with the cached access token, then STS | temporary credentials from `GetRoleCredentials` |
| `web_identity` | `role_arn`, `web_identity_token_file`, `session_name` | STS `AssumeRoleWithWebIdentity` with the token file, then `GetCallerIdentity` | `AWS_ROLE_ARN`, `AWS_WEB_IDENTITY_TOKEN_FILE`, `AWS_ROLE_SESSION_NAME` |

Identity returned by a test: `account`, `arn`, `user_id`, `region` and, for temporary
credentials, `credentials_expire_at`.

The SSO device flow: `device/start` registers a public client with `sso-oidc` and starts a
device authorization; the user opens `verification_uri_complete` and approves. `device/poll`
calls `CreateToken` until it returns a token, stores `sso_access_token` and
`sso_token_expires_at` encrypted in the connection, then runs a test (`GetRoleCredentials` +
STS) and sets the status. The access token typically lasts 8 hours; afterwards start the flow
again. The flow's own client secret and device code are stored encrypted in `device_flows` and
cleared when the flow finishes.

Temporary credentials resolved for `assume_role` and `sso` are cached in memory until five
minutes before they expire and are dropped whenever the connection changes.

### Azure

Common to every method: `subscription_id`, `tenant_id` (both required) and `environment`
(`public`, `usgovernment`, `china`; selects the authority host and the ARM endpoint, and sets
`ARM_ENVIRONMENT` when not public).

| method | fields | credential (azure-identity) | Terraform environment |
|---|---|---|---|
| `service_principal_secret` | `client_id`, `client_secret` (secret) | `ClientSecretCredential` | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET` |
| `service_principal_certificate` | `client_id`, `certificate_pem` (secret; PEM with certificate and key, or a base64 PFX), `certificate_password` (secret, optional) | `CertificateCredential` | `ARM_CLIENT_ID`, `ARM_CLIENT_CERTIFICATE` (base64 of the PEM, or the PFX as pasted), `ARM_CLIENT_CERTIFICATE_PASSWORD` |
| `managed_identity` | `client_id` (optional, user-assigned identity) | `ManagedIdentityCredential` | `ARM_USE_MSI=true`, `ARM_CLIENT_ID` |
| `oidc` | `client_id`, and `oidc_token` (secret) or `oidc_token_file_path` | `ClientAssertionCredential` (token) or `WorkloadIdentityCredential` (file) | `ARM_USE_OIDC=true`, `ARM_CLIENT_ID`, `ARM_OIDC_TOKEN` or `ARM_OIDC_TOKEN_FILE_PATH` |
| `cli` | none | `AzureCliCredential` from a mounted `~/.azure` | `ARM_USE_CLI=true` |
| `device_code` | `client_id` (optional; defaults to the Azure CLI public client) | `DeviceCodeCredential` | not Terraform-ready: `terraform_env` fails with "device-code sign-in verifies access; Terraform needs a service principal, managed identity, workload identity or CLI login" |

Verification requests a token for `{ARM}/.default` and reads
`GET {ARM}/subscriptions/{subscription_id}?api-version=2022-12-01`; the identity holds
`subscription_id`, `subscription_name`, `tenant_id`, `state`, `environment` and `client_id`.

OIDC tokens: in GitHub Actions request one with `ACTIONS_ID_TOKEN_REQUEST_URL` (audience
`api://AzureADTokenExchange`) and pass it as `oidc_token`; on Kubernetes with workload
identity point `oidc_token_file_path` at the projected token
(`/var/run/secrets/azure/tokens/azure-identity-token`). The federated credential on the app
registration must match the issuer and subject of the token.

The device-code flow: `device/start` creates a `DeviceCodeCredential` and runs
`authenticate()` in a background thread; the prompt callback supplies `user_code` and
`verification_uri` (`https://microsoft.com/devicelogin`). `device/poll` reports `pending` until
the thread finishes, then runs a test with the signed-in credential. The credential object
stays in memory only: the sign-in lasts for the lifetime of the process (a restart means
signing in again) and is never written to disk.

### Google Cloud

Common to every method: `project_id` (required; `GOOGLE_PROJECT`), `region` and `zone`
(optional; `GOOGLE_REGION`, `GOOGLE_ZONE`).

| method | fields | credentials (google-auth) | Terraform environment |
|---|---|---|---|
| `service_account_key` | `key_json` (secret) | `service_account.Credentials.from_service_account_info` | `GOOGLE_CREDENTIALS` (the JSON) |
| `adc` | `credentials_file` (optional) | `google.auth.load_credentials_from_file` or `google.auth.default()` (metadata server, `GOOGLE_APPLICATION_CREDENTIALS`, gcloud login) | `GOOGLE_APPLICATION_CREDENTIALS` when a file is set; nothing for the metadata server |
| `impersonation` | `target_service_account`, `base_method` (`adc` or `service_account_key`), `credentials_file` or `key_json` (secret) | `impersonated_credentials.Credentials` over the base credentials | `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT` plus the base method's variables |
| `workload_identity_federation` | `credential_config_json` (secret) | `google.auth.load_credentials_from_dict` (external account) | `GOOGLE_CREDENTIALS` (the configuration JSON) |

Verification refreshes an access token with the `cloud-platform` scope and reads
`GET https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}`; the identity holds
`project_id`, `project_name`, `project_number`, `state` and `principal` (the service account
email when known). `key_json` and `credential_config_json` must be JSON objects with a `type`.

### OpenStack

Common: `auth_url` (Keystone v3; `/v3` is appended when missing; `OS_AUTH_URL`), `region_name`
(`OS_REGION_NAME`) and `interface` (`OS_INTERFACE`), both optional.

| method | fields | verifies | Terraform environment |
|---|---|---|---|
| `password` | `username`, `password` (secret), `project_name`, `user_domain_name` and `project_domain_name` (default `Default`) | `POST {auth_url}/auth/tokens` with a project-scoped password auth | `OS_USERNAME`, `OS_PASSWORD`, `OS_PROJECT_NAME`, `OS_USER_DOMAIN_NAME`, `OS_PROJECT_DOMAIN_NAME`, `OS_IDENTITY_API_VERSION=3` |
| `application_credential` | `application_credential_id`, `application_credential_secret` (secret) | `POST {auth_url}/auth/tokens` with the application credential | `OS_AUTH_TYPE=v3applicationcredential`, `OS_APPLICATION_CREDENTIAL_ID`, `OS_APPLICATION_CREDENTIAL_SECRET` |
| `clouds_yaml` | `cloud`, `clouds_yaml_path` (optional), `auth_url` optional (overrides the file) | reads the named cloud from `clouds.yaml` and authenticates with its password or application credential | `OS_CLOUD`, `OS_CLIENT_CONFIG_FILE` when a path is set |

The identity holds `project_id`, `project_name`, `user_name`, `user_domain`, `services`
(catalog entries) and the token's `expires_at`. The Keystone token itself is discarded.

`clouds.yaml` is looked up at `clouds_yaml_path`, then `OS_CLIENT_CONFIG_FILE`, `./clouds.yaml`,
`~/.config/openstack/clouds.yaml` and `/etc/openstack/clouds.yaml`.

## Docker mounts

Methods that rely on files on the host need those files inside the container (the image runs
as `appuser`, home `/home/appuser`); mount them read-only in `docker-compose.yml`:

```yaml
services:
  vma:
    volumes:
      - ~/.aws:/home/appuser/.aws:ro                        # aws profile, sso cache
      - ~/.azure:/home/appuser/.azure:ro                    # azure cli
      - ~/.config/gcloud:/home/appuser/.config/gcloud:ro    # gcp adc (credentials_file: /home/appuser/.config/gcloud/application_default_credentials.json)
      - ~/.config/openstack:/home/appuser/.config/openstack:ro   # clouds.yaml
      - /var/run/secrets/tokens:/var/run/secrets/tokens:ro       # web identity / workload identity token files
```

Paths in `shared_credentials_file`, `config_file`, `credentials_file`, `web_identity_token_file`,
`oidc_token_file_path` and `clouds_yaml_path` are container paths (the compose file maps
`VMA_PORT`, default 8080, to the API). For `managed_identity`,
`environment` (instance role, IRSA) and the metadata-server flavour of `adc`, nothing is mounted:
the platform just needs to run on a host (VM, pod) that has the identity.

## LocalStack

Set `endpoint_url` to `http://localhost:4566` (or `http://localstack:4566` from Docker
Compose) on an AWS connection with any keys (`access_key_id: test`, `secret_access_key: test`,
`region: us-east-1`). The test calls STS on LocalStack and Terraform receives
`AWS_ENDPOINT_URL`, which the AWS provider (5.x and later) honours for every service. Terraform
also needs `skip_credentials_validation`, `skip_requesting_account_id` and
`s3_use_path_style` in the provider block for LocalStack; the deployments doc covers the
recipe.

## Security model

- Secrets are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) using the key in
  `VMA_SECRET_KEY` (generate one with `vma secrets generate-key`). The plaintext never reaches
  SQLite: `connections.secret_token` and `device_flows.secret_token` hold the ciphertext, and
  `connections.secret_keys` holds only field names. Without a key, connections with secret
  fields cannot be created (503 with instructions); methods without secrets still work.
- Key rotation: set `VMA_SECRET_KEY=<new>,<old>` and run `vma secrets rotate`
  (`ConnectionService.rotate_secrets()` re-encrypts every token with the first key).
- The API never returns a secret value: responses carry `has_secret` and `secret_fields` only;
  `GET` after a `PATCH` shows which fields are stored, not their contents. Device flow
  responses contain the user code and verification URI only.
- Secrets leave the service through two methods used by the deployment executor:
  `terraform_env(id)` (the variables above) and `secret_values(id)` (every stored secret plus
  resolved temporary credentials and derived values such as the base64 certificate, so Terraform
  logs can be masked).
- Test failures return a short message with secret values masked (`***`) and never echo
  request bodies; the audit log records who created, updated, deleted, tested or signed in to a
  connection (`connection.*` actions) with field names and outcomes only.
- The Azure device-code credential and the AWS temporary credential cache live in process
  memory and are dropped when the connection is updated or deleted.
