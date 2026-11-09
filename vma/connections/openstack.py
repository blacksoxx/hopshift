"""OpenStack connections: Keystone v3 verification and the Terraform `OS_*` variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from .models import ResolvedEnv, VerifyResult

SECRET_ENV_KEYS: tuple[str, ...] = ("OS_PASSWORD", "OS_APPLICATION_CREDENTIAL_SECRET")
CLOUDS_YAML_LOCATIONS: tuple[str, ...] = ("clouds.yaml", "~/.config/openstack/clouds.yaml", "/etc/openstack/clouds.yaml")


def normalise_auth_url(auth_url: str) -> str:
    url = auth_url.strip().rstrip("/")
    if not url.endswith("/v3"):
        url = f"{url}/v3"
    return url


# ── clouds.yaml ───────────────────────────────────────────────────────────────


def clouds_yaml_path(config: dict[str, Any]) -> Path:
    if config.get("clouds_yaml_path"):
        return Path(str(config["clouds_yaml_path"])).expanduser()
    env_path = os.environ.get("OS_CLIENT_CONFIG_FILE")
    candidates = [Path(env_path).expanduser()] if env_path else []
    candidates.extend(Path(item).expanduser() for item in CLOUDS_YAML_LOCATIONS)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("clouds.yaml not found; mount it or set clouds_yaml_path")


def load_cloud(config: dict[str, Any]) -> dict[str, Any]:
    path = clouds_yaml_path(config)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    clouds = data.get("clouds") if isinstance(data, dict) else None
    name = str(config.get("cloud") or "")
    if not isinstance(clouds, dict) or name not in clouds:
        raise RuntimeError(f"cloud {name!r} is not defined in {path}")
    cloud = clouds[name] or {}
    if not isinstance(cloud, dict):
        raise RuntimeError(f"cloud {name!r} in {path} is malformed")
    return cloud


def clouds_yaml_secret_values(config: dict[str, Any]) -> list[str]:
    try:
        auth = load_cloud(config).get("auth") or {}
    except Exception:  # noqa: BLE001 - masking is best effort when the file is missing
        return []
    return [str(auth[key]) for key in ("password", "application_credential_secret") if auth.get(key)]


# ── Keystone ──────────────────────────────────────────────────────────────────


def auth_request(auth_method: str, config: dict[str, Any], secret: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """The Keystone v3 auth URL and request body for the method."""
    if auth_method == "password":
        body = {"auth": {
            "identity": {"methods": ["password"], "password": {"user": {
                "name": str(config["username"]), "domain": {"name": str(config.get("user_domain_name") or "Default")}, "password": str(secret["password"]),
            }}},
            "scope": {"project": {"name": str(config["project_name"]), "domain": {"name": str(config.get("project_domain_name") or "Default")}}},
        }}
        return normalise_auth_url(str(config["auth_url"])), body
    if auth_method == "application_credential":
        body = {"auth": {"identity": {"methods": ["application_credential"], "application_credential": {
            "id": str(config["application_credential_id"]), "secret": str(secret["application_credential_secret"]),
        }}}}
        return normalise_auth_url(str(config["auth_url"])), body
    if auth_method == "clouds_yaml":
        cloud = load_cloud(config)
        auth = cloud.get("auth") or {}
        auth_url = str(config.get("auth_url") or auth.get("auth_url") or "")
        if not auth_url:
            raise RuntimeError("clouds.yaml entry has no auth_url")
        if auth.get("application_credential_id") and auth.get("application_credential_secret"):
            body = {"auth": {"identity": {"methods": ["application_credential"], "application_credential": {
                "id": str(auth["application_credential_id"]), "secret": str(auth["application_credential_secret"]),
            }}}}
            return normalise_auth_url(auth_url), body
        if auth.get("username") and auth.get("password"):
            user: dict[str, Any] = {"name": str(auth["username"]), "password": str(auth["password"])}
            if auth.get("user_domain_id"):
                user["domain"] = {"id": str(auth["user_domain_id"])}
            else:
                user["domain"] = {"name": str(auth.get("user_domain_name") or "Default")}
            scope: dict[str, Any] = {}
            if auth.get("project_id"):
                scope = {"project": {"id": str(auth["project_id"])}}
            elif auth.get("project_name"):
                domain = {"id": str(auth["project_domain_id"])} if auth.get("project_domain_id") else {"name": str(auth.get("project_domain_name") or "Default")}
                scope = {"project": {"name": str(auth["project_name"]), "domain": domain}}
            body = {"auth": {"identity": {"methods": ["password"], "password": {"user": user}}}}
            if scope:
                body["auth"]["scope"] = scope
            return normalise_auth_url(auth_url), body
        raise RuntimeError("clouds.yaml entry has neither a password nor an application credential")
    raise ValueError(f"unsupported OpenStack auth method {auth_method!r}")


def keystone_authenticate(auth_url: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /auth/tokens; returns the `token` object (never the subject token header)."""
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{auth_url}/auth/tokens", json=body, headers={"Accept": "application/json"})
    if response.status_code == 401:
        raise RuntimeError("Keystone rejected the credentials (401)")
    response.raise_for_status()
    token = response.json().get("token") or {}
    return token if isinstance(token, dict) else {}


# ── service entry points ──────────────────────────────────────────────────────


def verify(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> VerifyResult:
    auth_url, body = auth_request(auth_method, config, secret)
    token = keystone_authenticate(auth_url, body)
    project = token.get("project") or {}
    user = token.get("user") or {}
    identity = {
        "project_id": project.get("id"), "project_name": project.get("name"), "user_name": user.get("name"),
        "user_domain": (user.get("domain") or {}).get("name"), "services": len(token.get("catalog") or []),
        "expires_at": token.get("expires_at"), "auth_url": auth_url,
    }
    if config.get("region_name"):
        identity["region"] = config["region_name"]
    label = f"{identity['user_name']}@{identity['project_name']}" if identity.get("user_name") else identity.get("project_name") or auth_url
    return VerifyResult(True, identity, f"authenticated as {label}")


def terraform_env(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> ResolvedEnv:
    env: dict[str, str] = {}
    if config.get("auth_url"):
        env["OS_AUTH_URL"] = normalise_auth_url(str(config["auth_url"]))
    if config.get("region_name"):
        env["OS_REGION_NAME"] = str(config["region_name"])
    if config.get("interface"):
        env["OS_INTERFACE"] = str(config["interface"])
    if auth_method == "password":
        env.update({
            "OS_USERNAME": str(config["username"]), "OS_PASSWORD": str(secret["password"]), "OS_PROJECT_NAME": str(config["project_name"]),
            "OS_USER_DOMAIN_NAME": str(config.get("user_domain_name") or "Default"), "OS_PROJECT_DOMAIN_NAME": str(config.get("project_domain_name") or "Default"),
            "OS_IDENTITY_API_VERSION": "3",
        })
    elif auth_method == "application_credential":
        env.update({
            "OS_AUTH_TYPE": "v3applicationcredential",
            "OS_APPLICATION_CREDENTIAL_ID": str(config["application_credential_id"]),
            "OS_APPLICATION_CREDENTIAL_SECRET": str(secret["application_credential_secret"]),
            "OS_IDENTITY_API_VERSION": "3",
        })
    elif auth_method == "clouds_yaml":
        env["OS_CLOUD"] = str(config["cloud"])
        if config.get("clouds_yaml_path"):
            env["OS_CLIENT_CONFIG_FILE"] = str(config["clouds_yaml_path"])
    else:
        raise ValueError(f"unsupported OpenStack auth method {auth_method!r}")
    return ResolvedEnv(env, None)
