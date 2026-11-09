"""Google Cloud connections: google-auth credentials, Resource Manager verification and the
Terraform `GOOGLE_*` variables.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .models import ResolvedEnv, VerifyResult

SECRET_ENV_KEYS: tuple[str, ...] = ("GOOGLE_CREDENTIALS",)
SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
RESOURCE_MANAGER = "https://cloudresourcemanager.googleapis.com/v1/projects"


# ── credentials (stubbed in tests) ────────────────────────────────────────────


def _principal(credentials: Any) -> str | None:
    for attr in ("service_account_email", "signer_email"):
        value = getattr(credentials, attr, None)
        if isinstance(value, str) and value and value != "default":
            return value
    return None


def _base_credentials(base_method: str, config: dict[str, Any], secret: dict[str, Any]) -> tuple[Any, str | None]:
    import google.auth
    from google.oauth2 import service_account

    scopes = list(SCOPES)
    if base_method == "service_account_key":
        info = json.loads(str(secret["key_json"]))
        credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        return credentials, str(info.get("client_email") or "") or None
    if base_method == "adc":
        if config.get("credentials_file"):
            credentials, _project = google.auth.load_credentials_from_file(str(config["credentials_file"]), scopes=scopes)
        else:
            credentials, _project = google.auth.default(scopes=scopes)
        return credentials, _principal(credentials)
    raise ValueError(f"unsupported base credentials {base_method!r}")


def build_credentials(auth_method: str, config: dict[str, Any], secret: dict[str, Any]) -> tuple[Any, str | None]:
    """Credentials for the method and the principal email when it is known up front."""
    if auth_method in {"service_account_key", "adc"}:
        return _base_credentials(auth_method, config, secret)
    if auth_method == "impersonation":
        from google.auth import impersonated_credentials

        source, _ = _base_credentials(str(config.get("base_method") or "adc"), config, secret)
        target = str(config["target_service_account"])
        credentials = impersonated_credentials.Credentials(source_credentials=source, target_principal=target, target_scopes=list(SCOPES), lifetime=3600)
        return credentials, target
    if auth_method == "workload_identity_federation":
        import google.auth

        info = json.loads(str(secret["credential_config_json"]))
        credentials, _project = google.auth.load_credentials_from_dict(info, scopes=list(SCOPES))
        return credentials, _principal(credentials)
    raise ValueError(f"unsupported GCP auth method {auth_method!r}")


def refresh_token(credentials: Any) -> str:
    from google.auth.transport.requests import Request

    credentials.refresh(Request())
    return str(credentials.token)


def get_project(token: str, project_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{RESOURCE_MANAGER}/{project_id}", headers={"Authorization": f"Bearer {token}"})
    if response.status_code in {403, 404}:
        raise RuntimeError(f"project {project_id} was not found or the principal has no resourcemanager.projects.get permission")
    response.raise_for_status()
    body = response.json()
    return {"project_id": body.get("projectId"), "project_name": body.get("name"), "project_number": body.get("projectNumber"), "state": body.get("lifecycleState")}


# ── service entry points ──────────────────────────────────────────────────────


def verify(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> VerifyResult:
    credentials, principal = build_credentials(auth_method, config, secret)
    token = refresh_token(credentials)
    identity = get_project(token, str(config["project_id"]))
    identity["principal"] = principal or _principal(credentials)
    return VerifyResult(True, identity, f"authenticated to project {identity.get('project_id') or config.get('project_id')}")


def terraform_env(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> ResolvedEnv:
    env: dict[str, str] = {"GOOGLE_PROJECT": str(config["project_id"])}
    if config.get("region"):
        env["GOOGLE_REGION"] = str(config["region"])
    if config.get("zone"):
        env["GOOGLE_ZONE"] = str(config["zone"])
    if auth_method == "service_account_key":
        env["GOOGLE_CREDENTIALS"] = _compact(secret["key_json"])
    elif auth_method == "adc":
        if config.get("credentials_file"):
            env["GOOGLE_APPLICATION_CREDENTIALS"] = str(config["credentials_file"])
    elif auth_method == "impersonation":
        env["GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"] = str(config["target_service_account"])
        if str(config.get("base_method") or "adc") == "service_account_key":
            env["GOOGLE_CREDENTIALS"] = _compact(secret["key_json"])
        elif config.get("credentials_file"):
            env["GOOGLE_APPLICATION_CREDENTIALS"] = str(config["credentials_file"])
    elif auth_method == "workload_identity_federation":
        env["GOOGLE_CREDENTIALS"] = _compact(secret["credential_config_json"])
    else:
        raise ValueError(f"unsupported GCP auth method {auth_method!r}")
    return ResolvedEnv(env, None)


def _compact(text: Any) -> str:
    try:
        return json.dumps(json.loads(str(text)), separators=(",", ":"))
    except ValueError:
        return str(text)
