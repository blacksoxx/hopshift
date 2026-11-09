"""Connection record and the catalog of providers, auth methods and their fields.

The catalog is the single description of what a connection can hold: the API serves it so the
UI renders forms generically, and the service validates `config` and `secret` against it.
Fields marked `secret` are stored encrypted (see vma.secrets) and never returned by the API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

from vma.secrets import mask_values

PROVIDERS: tuple[str, ...] = ("aws", "azure", "gcp", "openstack")
STATUSES: tuple[str, ...] = ("unverified", "ok", "failed")
FIELD_TYPES: tuple[str, ...] = ("text", "password", "textarea", "select", "boolean", "number")

AZURE_CLI_PUBLIC_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
DEFAULT_SESSION_NAME = "vmware-migration-agent"


@dataclass
class Connection:
    id: str
    name: str
    provider: str
    auth_method: str
    config: dict[str, Any]
    secret_token: str | None
    secret_keys: list[str]
    status: str
    last_checked_at: str | None
    last_check: dict[str, Any] | None
    created_by: str | None
    created_at: str
    updated_at: str

    @property
    def has_secret(self) -> bool:
        return bool(self.secret_token)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    identity: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass(frozen=True)
class ResolvedEnv:
    """Environment variables for Terraform plus the expiry of any temporary credentials in it."""
    env: dict[str, str]
    expires_at: str | None = None  # ISO timestamp (UTC) when temporary credentials expire


def safe_error(exc: BaseException, secrets: Iterable[str] = ()) -> str:
    """A short, single-line description of an exception with secret values masked."""
    code = ""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):  # botocore.exceptions.ClientError
        error = response.get("Error") or {}
        code = str(error.get("Code") or "")
        text = str(error.get("Message") or exc)
    elif hasattr(response, "status_code"):  # httpx.HTTPStatusError
        text = f"HTTP {response.status_code} from {response.url.host}" if getattr(response, "url", None) else f"HTTP {response.status_code}"
    else:
        text = str(exc) or type(exc).__name__
    text = " ".join(text.split())
    if code:
        text = f"{code}: {text}"
    elif type(exc) not in (RuntimeError, ValueError) and type(exc).__name__ not in text:
        # our own RuntimeError/ValueError messages are already descriptive; SDK and OS errors are not
        text = f"{type(exc).__name__}: {text}"
    text = mask_values(text, [value for value in secrets if isinstance(value, str)])
    return text[:300]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str = "text"
    required: bool = False
    secret: bool = False
    help: str = ""
    options: tuple[tuple[str, str], ...] = ()  # (value, label)
    placeholder: str = ""
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "key": self.key, "label": self.label, "type": self.type, "required": self.required,
            "secret": self.secret, "help": self.help,
        }
        if self.options:
            item["options"] = [{"value": value, "label": label} for value, label in self.options]
        if self.placeholder:
            item["placeholder"] = self.placeholder
        if self.default is not None:
            item["default"] = self.default
        return item


# A method-level validator receives the merged (config, secret) and returns a list of problems.
Validator = Callable[[dict[str, Any], dict[str, Any]], list[str]]


@dataclass(frozen=True)
class MethodSpec:
    key: str
    label: str
    description: str
    fields: tuple[FieldSpec, ...]
    terraform_ready: bool = True
    device_flow: bool = False
    validators: tuple[Validator, ...] = ()
    # Secret keys written by the service itself (device flows), never accepted from callers.
    internal_secret_keys: tuple[str, ...] = ()

    def field(self, key: str) -> FieldSpec | None:
        return next((item for item in self.fields if item.key == key), None)

    @property
    def config_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(item for item in self.fields if not item.secret)

    @property
    def secret_fields(self) -> tuple[FieldSpec, ...]:
        return tuple(item for item in self.fields if item.secret)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "description": self.description,
            "terraform_ready": self.terraform_ready, "device_flow": self.device_flow,
            "fields": [item.to_dict() for item in self.fields],
        }


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    methods: tuple[MethodSpec, ...]

    def method(self, key: str) -> MethodSpec | None:
        return next((item for item in self.methods if item.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "methods": [item.to_dict() for item in self.methods]}


# ── shared field definitions ──────────────────────────────────────────────────

_AWS_REGION = FieldSpec("region", "Region", required=True, placeholder="eu-west-1", help="Default region for Terraform (AWS_REGION).")
_AWS_ENDPOINT = FieldSpec("endpoint_url", "Endpoint URL", help="Optional. Custom endpoint for LocalStack or private endpoints (AWS_ENDPOINT_URL).", placeholder="http://localhost:4566")
_AWS_SESSION_NAME = FieldSpec("session_name", "Session name", default=DEFAULT_SESSION_NAME, help="Role session name shown in CloudTrail.")
_AWS_KEY_ID = FieldSpec("access_key_id", "Access key ID", placeholder="AKIA...")
_AWS_SECRET_KEY = FieldSpec("secret_access_key", "Secret access key", type="password", secret=True)
_AWS_SESSION_TOKEN = FieldSpec("session_token", "Session token", type="password", secret=True, help="Optional. Only for temporary credentials.")
_AWS_PROFILE = FieldSpec("profile", "Profile", placeholder="default", help="Named profile from a mounted ~/.aws (AWS_PROFILE).")
_AWS_CRED_FILE = FieldSpec("shared_credentials_file", "Shared credentials file", help="Optional. Path to the credentials file when it is not ~/.aws/credentials.")
_AWS_CONFIG_FILE = FieldSpec("config_file", "Config file", help="Optional. Path to the config file when it is not ~/.aws/config.")

_AZURE_COMMON: tuple[FieldSpec, ...] = (
    FieldSpec("subscription_id", "Subscription ID", required=True, placeholder="00000000-0000-0000-0000-000000000000"),
    FieldSpec("tenant_id", "Tenant ID", required=True, placeholder="00000000-0000-0000-0000-000000000000"),
    FieldSpec("environment", "Cloud environment", type="select", default="public",
              options=(("public", "Azure public cloud"), ("usgovernment", "Azure US Government"), ("china", "Azure China")),
              help="Selects the authority host and ARM endpoint (ARM_ENVIRONMENT)."),
)
_AZURE_CLIENT_ID = FieldSpec("client_id", "Client ID", required=True, placeholder="00000000-0000-0000-0000-000000000000", help="Application (client) ID of the service principal.")

_GCP_COMMON: tuple[FieldSpec, ...] = (
    FieldSpec("project_id", "Project ID", required=True, placeholder="my-project-123456", help="GOOGLE_PROJECT for Terraform; verification reads this project."),
    FieldSpec("region", "Region", placeholder="europe-west1", help="Optional default region (GOOGLE_REGION)."),
    FieldSpec("zone", "Zone", placeholder="europe-west1-b", help="Optional default zone (GOOGLE_ZONE)."),
)
_GCP_KEY_JSON = FieldSpec("key_json", "Service account key (JSON)", type="textarea", secret=True, help="Contents of the downloaded service account key file.")
_GCP_CREDENTIALS_FILE = FieldSpec("credentials_file", "Credentials file", help="Optional. Path to an application default credentials file inside the container (e.g. a mounted ~/.config/gcloud/application_default_credentials.json). Without it the metadata server or GOOGLE_APPLICATION_CREDENTIALS is used.")

_OPENSTACK_COMMON: tuple[FieldSpec, ...] = (
    FieldSpec("auth_url", "Auth URL", required=True, placeholder="https://keystone.example.com:5000/v3", help="Keystone v3 endpoint (OS_AUTH_URL)."),
    FieldSpec("region_name", "Region", placeholder="RegionOne", help="Optional (OS_REGION_NAME)."),
    FieldSpec("interface", "Endpoint interface", type="select", options=(("public", "public"), ("internal", "internal"), ("admin", "admin")), help="Optional (OS_INTERFACE)."),
)


# ── method-level validators ───────────────────────────────────────────────────


def _present(values: dict[str, Any], key: str) -> bool:
    value = values.get(key)
    return value is not None and str(value).strip() != ""


def _aws_assume_role_base(config: dict[str, Any], secret: dict[str, Any]) -> list[str]:
    base = str(config.get("base_method") or "access_keys")
    problems: list[str] = []
    if base == "access_keys":
        if not _present(config, "access_key_id"):
            problems.append("access_key_id is required when base_method is access_keys")
        if not _present(secret, "secret_access_key"):
            problems.append("secret_access_key is required when base_method is access_keys")
    elif base == "profile" and not _present(config, "profile"):
        problems.append("profile is required when base_method is profile")
    return problems


def _azure_oidc_token_source(config: dict[str, Any], secret: dict[str, Any]) -> list[str]:
    if not _present(secret, "oidc_token") and not _present(config, "oidc_token_file_path"):
        return ["one of oidc_token or oidc_token_file_path is required"]
    return []


def _gcp_impersonation_base(config: dict[str, Any], secret: dict[str, Any]) -> list[str]:
    if str(config.get("base_method") or "adc") == "service_account_key" and not _present(secret, "key_json"):
        return ["key_json is required when base_method is service_account_key"]
    return []


def _gcp_json_secrets(config: dict[str, Any], secret: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for key in ("key_json", "credential_config_json"):
        if not _present(secret, key):
            continue
        try:
            parsed = json.loads(str(secret[key]))
        except ValueError:
            problems.append(f"{key} is not valid JSON")
            continue
        if not isinstance(parsed, dict) or not parsed.get("type"):
            problems.append(f"{key} must be a JSON object with a `type` field")
    return problems


# ── the catalog ───────────────────────────────────────────────────────────────

CATALOG: dict[str, ProviderSpec] = {
    "aws": ProviderSpec("aws", "Amazon Web Services", (
        MethodSpec(
            "access_keys", "Access keys",
            "A long-lived or temporary access key pair.",
            (replace(_AWS_KEY_ID, required=True), replace(_AWS_SECRET_KEY, required=True), _AWS_SESSION_TOKEN, _AWS_REGION, _AWS_ENDPOINT),
        ),
        MethodSpec(
            "profile", "Named profile",
            "A profile from a mounted ~/.aws directory (credentials and config files).",
            (replace(_AWS_PROFILE, required=True), _AWS_REGION, _AWS_CRED_FILE, _AWS_CONFIG_FILE, _AWS_ENDPOINT),
        ),
        MethodSpec(
            "assume_role", "Assume role",
            "Assume an IAM role with STS from base credentials (keys, a profile or the process environment).",
            (
                FieldSpec("base_method", "Base credentials", type="select", required=True, default="access_keys",
                          options=(("access_keys", "Access keys"), ("profile", "Named profile"), ("environment", "Process environment"))),
                _AWS_KEY_ID, _AWS_SECRET_KEY, _AWS_SESSION_TOKEN, _AWS_PROFILE, _AWS_CRED_FILE, _AWS_CONFIG_FILE,
                FieldSpec("role_arn", "Role ARN", required=True, placeholder="arn:aws:iam::123456789012:role/migration"),
                FieldSpec("external_id", "External ID", help="Optional. Required by some cross-account trust policies."),
                _AWS_SESSION_NAME, _AWS_REGION, _AWS_ENDPOINT,
            ),
            validators=(_aws_assume_role_base,),
        ),
        MethodSpec(
            "environment", "Process environment",
            "Credentials the process already has: environment variables, an instance role, ECS task role or IRSA.",
            (_AWS_REGION, _AWS_ENDPOINT),
        ),
        MethodSpec(
            "sso", "IAM Identity Center (SSO)",
            "Device authorization through sso-oidc; the cached access token resolves role credentials on demand.",
            (
                FieldSpec("start_url", "Start URL", required=True, placeholder="https://my-org.awsapps.com/start"),
                FieldSpec("sso_region", "SSO region", required=True, placeholder="eu-west-1", help="Region of the IAM Identity Center instance."),
                FieldSpec("account_id", "Account ID", required=True, placeholder="123456789012"),
                FieldSpec("role_name", "Permission set / role name", required=True, placeholder="AdministratorAccess"),
                _AWS_REGION, _AWS_ENDPOINT,
            ),
            device_flow=True,
            internal_secret_keys=("sso_access_token", "sso_token_expires_at"),
        ),
        MethodSpec(
            "web_identity", "Web identity",
            "Assume a role with a web identity token file (Kubernetes IRSA, GitLab/GitHub OIDC).",
            (
                FieldSpec("role_arn", "Role ARN", required=True, placeholder="arn:aws:iam::123456789012:role/migration"),
                FieldSpec("web_identity_token_file", "Web identity token file", required=True, placeholder="/var/run/secrets/eks.amazonaws.com/serviceaccount/token"),
                _AWS_SESSION_NAME, _AWS_REGION, _AWS_ENDPOINT,
            ),
        ),
    )),
    "azure": ProviderSpec("azure", "Microsoft Azure", (
        MethodSpec(
            "service_principal_secret", "Service principal (client secret)",
            "An app registration with a client secret.",
            (*_AZURE_COMMON, _AZURE_CLIENT_ID, FieldSpec("client_secret", "Client secret", type="password", required=True, secret=True)),
        ),
        MethodSpec(
            "service_principal_certificate", "Service principal (certificate)",
            "An app registration with a certificate credential.",
            (*_AZURE_COMMON, _AZURE_CLIENT_ID,
             FieldSpec("certificate_pem", "Certificate", type="textarea", required=True, secret=True,
                       help="PEM with the certificate and private key, or a base64-encoded PFX bundle."),
             FieldSpec("certificate_password", "Certificate password", type="password", secret=True, help="Optional. Password of the private key or PFX.")),
        ),
        MethodSpec(
            "managed_identity", "Managed identity",
            "The system-assigned or a user-assigned managed identity of the host.",
            (*_AZURE_COMMON, FieldSpec("client_id", "Client ID", help="Optional. Client ID of a user-assigned identity; empty for the system-assigned identity.")),
        ),
        MethodSpec(
            "oidc", "Workload identity federation (OIDC)",
            "Federated credential: a token from GitHub Actions, GitLab CI or Kubernetes workload identity is exchanged for an Azure token.",
            (*_AZURE_COMMON, _AZURE_CLIENT_ID,
             FieldSpec("oidc_token", "OIDC token", type="textarea", secret=True, help="A JWT issued by the federated identity provider (GitHub Actions: request it with ACTIONS_ID_TOKEN_REQUEST_URL; GitLab: an id_token). Short-lived; prefer the file path on Kubernetes."),
             FieldSpec("oidc_token_file_path", "OIDC token file path", help="Path to a projected token file (Kubernetes workload identity: /var/run/secrets/azure/tokens/azure-identity-token).")),
            validators=(_azure_oidc_token_source,),
        ),
        MethodSpec(
            "cli", "Azure CLI",
            "The signed-in Azure CLI from a mounted ~/.azure directory.",
            _AZURE_COMMON,
        ),
        MethodSpec(
            "device_code", "Device code sign-in",
            "Interactive sign-in with a user account. Verifies access only; Terraform needs a service principal, managed identity, workload identity or CLI login.",
            (*_AZURE_COMMON, FieldSpec("client_id", "Client ID", default=AZURE_CLI_PUBLIC_CLIENT_ID, help="Optional. Public client application ID; defaults to the Azure CLI application.")),
            terraform_ready=False,
            device_flow=True,
        ),
    )),
    "gcp": ProviderSpec("gcp", "Google Cloud", (
        MethodSpec(
            "service_account_key", "Service account key",
            "A service account key file (JSON).",
            (*_GCP_COMMON, replace(_GCP_KEY_JSON, required=True)),
            validators=(_gcp_json_secrets,),
        ),
        MethodSpec(
            "adc", "Application default credentials",
            "Credentials found by the Google auth library: a mounted gcloud login, GOOGLE_APPLICATION_CREDENTIALS or the metadata server.",
            (*_GCP_COMMON, _GCP_CREDENTIALS_FILE),
        ),
        MethodSpec(
            "impersonation", "Service account impersonation",
            "Base credentials (ADC or a key) impersonate a target service account.",
            (*_GCP_COMMON,
             FieldSpec("target_service_account", "Target service account", required=True, placeholder="terraform@my-project.iam.gserviceaccount.com"),
             FieldSpec("base_method", "Base credentials", type="select", required=True, default="adc",
                       options=(("adc", "Application default credentials"), ("service_account_key", "Service account key"))),
             _GCP_CREDENTIALS_FILE, _GCP_KEY_JSON),
            validators=(_gcp_impersonation_base, _gcp_json_secrets),
        ),
        MethodSpec(
            "workload_identity_federation", "Workload identity federation",
            "An external account credential configuration (AWS, Azure, OIDC or executable sourced).",
            (*_GCP_COMMON, FieldSpec("credential_config_json", "Credential configuration (JSON)", type="textarea", required=True, secret=True,
                                     help="The JSON produced by `gcloud iam workload-identity-pools create-cred-config`.")),
            validators=(_gcp_json_secrets,),
        ),
    )),
    "openstack": ProviderSpec("openstack", "OpenStack", (
        MethodSpec(
            "password", "Password",
            "Keystone v3 username and password scoped to a project.",
            (*_OPENSTACK_COMMON,
             FieldSpec("username", "Username", required=True),
             FieldSpec("password", "Password", type="password", required=True, secret=True),
             FieldSpec("project_name", "Project name", required=True),
             FieldSpec("user_domain_name", "User domain name", default="Default"),
             FieldSpec("project_domain_name", "Project domain name", default="Default")),
        ),
        MethodSpec(
            "application_credential", "Application credential",
            "A Keystone application credential (id and secret).",
            (*_OPENSTACK_COMMON,
             FieldSpec("application_credential_id", "Application credential ID", required=True),
             FieldSpec("application_credential_secret", "Application credential secret", type="password", required=True, secret=True)),
        ),
        MethodSpec(
            "clouds_yaml", "clouds.yaml",
            "A named cloud from a mounted clouds.yaml.",
            (FieldSpec("auth_url", "Auth URL", placeholder="https://keystone.example.com:5000/v3", help="Optional. Overrides the auth_url from clouds.yaml."),
             _OPENSTACK_COMMON[1], _OPENSTACK_COMMON[2],
             FieldSpec("cloud", "Cloud name", required=True, placeholder="mycloud", help="Key under `clouds:` (OS_CLOUD)."),
             FieldSpec("clouds_yaml_path", "clouds.yaml path", help="Optional. Path to the file when it is not in the default locations (OS_CLIENT_CONFIG_FILE).")),
        ),
    )),
}


def catalog_dict() -> dict[str, Any]:
    return {key: spec.to_dict() for key, spec in CATALOG.items()}


def method_spec(provider: str, auth_method: str) -> MethodSpec:
    """Look up a method; raises ValueError with a message safe to show to the caller."""
    provider_spec = CATALOG.get(provider)
    if provider_spec is None:
        raise ValueError(f"unknown provider {provider!r}; known: {', '.join(CATALOG)}")
    spec = provider_spec.method(auth_method)
    if spec is None:
        raise ValueError(f"unknown auth method {auth_method!r} for {provider}; known: {', '.join(item.key for item in provider_spec.methods)}")
    return spec


def validate_against_catalog(spec: MethodSpec, config: dict[str, Any], secret: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check and normalise `config` and `secret` for a method.

    Returns cleaned copies (defaults applied, strings stripped, empty values dropped). Raises
    ValueError listing every problem; the service wraps it into vma.errors.Invalid.
    """
    problems: list[str] = []
    cleaned_config: dict[str, Any] = {}
    cleaned_secret: dict[str, Any] = {}
    allowed_secret = {item.key for item in spec.secret_fields} | set(spec.internal_secret_keys)

    for key in config:
        field_spec = spec.field(key)
        if field_spec is None:
            problems.append(f"unknown field {key!r}")
        elif field_spec.secret:
            problems.append(f"field {key!r} is secret; send it in `secret`")
    for key in secret:
        if key not in allowed_secret:
            field_spec = spec.field(key)
            problems.append(f"field {key!r} is not a secret field" if field_spec else f"unknown secret field {key!r}")

    for field_spec in spec.fields:
        source = secret if field_spec.secret else config
        raw = source.get(field_spec.key)
        value = _normalise(field_spec, raw, problems)
        if value is None and field_spec.default is not None:
            value = field_spec.default
        if value is None:
            if field_spec.required:
                problems.append(f"{field_spec.key} is required")
            continue
        (cleaned_secret if field_spec.secret else cleaned_config)[field_spec.key] = value
    for key in spec.internal_secret_keys:
        if secret.get(key) not in (None, ""):
            cleaned_secret[key] = secret[key]

    if not problems:
        for validator in spec.validators:
            problems.extend(validator(cleaned_config, cleaned_secret))
    if problems:
        raise ValueError("; ".join(problems))
    return cleaned_config, cleaned_secret


def _normalise(field_spec: FieldSpec, raw: Any, problems: list[str]) -> Any:
    if raw is None:
        return None
    if field_spec.type == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
            return raw.strip().lower() == "true"
        problems.append(f"{field_spec.key} must be a boolean")
        return None
    if field_spec.type == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            problems.append(f"{field_spec.key} must be a number")
            return None
        try:
            return int(raw) if str(raw).strip().lstrip("-").isdigit() else float(raw)
        except ValueError:
            problems.append(f"{field_spec.key} must be a number")
            return None
    if not isinstance(raw, str):
        problems.append(f"{field_spec.key} must be a string")
        return None
    value = raw.strip() if field_spec.type != "textarea" else raw.strip("\r\n")
    if value == "":
        return None
    if field_spec.type == "select" and value not in {option for option, _ in field_spec.options}:
        problems.append(f"{field_spec.key} must be one of {', '.join(option for option, _ in field_spec.options)}")
        return None
    if len(value) > 65536:
        problems.append(f"{field_spec.key} is too long")
        return None
    return value
