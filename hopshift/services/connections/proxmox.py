"""Proxmox VE connections: API token or ticket verification against `/api2/json` and the Terraform
`PROXMOX_VE_*` variables read by the bpg/proxmox provider.
"""
from __future__ import annotations

from typing import Any

import httpx

from .models import ResolvedEnv, VerifyResult

SECRET_ENV_KEYS: tuple[str, ...] = ("PROXMOX_VE_API_TOKEN", "PROXMOX_VE_PASSWORD")
API_PATH = "/api2/json"


def normalise_endpoint(endpoint: str) -> str:
    """`https://pve.example.internal:8006` without a trailing slash or `/api2/json` suffix."""
    url = endpoint.strip().rstrip("/")
    if url.lower().endswith(API_PATH):
        url = url[: -len(API_PATH)].rstrip("/")
    return url


def api_token(token_id: str, token_secret: str) -> str:
    """The provider's PROXMOX_VE_API_TOKEN value: `user@realm!tokenname=secret`."""
    return f"{token_id.strip()}={token_secret}"


# ── HTTP (the client factory is replaced in tests) ────────────────────────────


def _client(insecure: bool) -> httpx.Client:
    return httpx.Client(timeout=30.0, verify=not insecure, headers={"Accept": "application/json"})


def _data(response: httpx.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    return body.get("data") if isinstance(body, dict) else None


def login(client: httpx.Client, endpoint: str, username: str, password: str) -> dict[str, str]:
    """POST /access/ticket; returns the request headers for the ticket (the ticket itself is never stored)."""
    response = client.post(f"{endpoint}{API_PATH}/access/ticket", data={"username": username, "password": password})
    if response.status_code == 401:
        raise RuntimeError("Proxmox VE rejected the username or password (401)")
    data = _data(response) or {}
    ticket = str(data.get("ticket") or "")
    if not ticket:
        raise RuntimeError("Proxmox VE returned no authentication ticket")
    return {"Cookie": f"PVEAuthCookie={ticket}", "CSRFPreventionToken": str(data.get("CSRFPreventionToken") or "")}


def auth_headers(client: httpx.Client, auth_method: str, endpoint: str, config: dict[str, Any], secret: dict[str, Any]) -> dict[str, str]:
    if auth_method == "api_token":
        return {"Authorization": f"PVEAPIToken={api_token(str(config['token_id']), str(secret['token_secret']))}"}
    if auth_method == "password":
        return login(client, endpoint, str(config["username"]), str(secret["password"]))
    raise ValueError(f"unsupported Proxmox VE auth method {auth_method!r}")


def get_version(client: httpx.Client, endpoint: str, headers: dict[str, str]) -> dict[str, Any]:
    """GET /version: the first call every credential must be able to make."""
    response = client.get(f"{endpoint}{API_PATH}/version", headers=headers)
    if response.status_code == 401:
        raise RuntimeError("Proxmox VE rejected the credentials (401)")
    data = _data(response)
    return data if isinstance(data, dict) else {}


def get_nodes(client: httpx.Client, endpoint: str, headers: dict[str, str]) -> list[dict[str, Any]] | None:
    """GET /nodes; None when the principal may not list nodes (Sys.Audit on /nodes is missing)."""
    response = client.get(f"{endpoint}{API_PATH}/nodes", headers=headers)
    if response.status_code in {401, 403}:
        return None
    data = _data(response)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else None


def principal(auth_method: str, config: dict[str, Any]) -> str:
    return str(config.get("token_id") if auth_method == "api_token" else config.get("username") or "")


# ── service entry points ──────────────────────────────────────────────────────


def verify(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> VerifyResult:
    endpoint = normalise_endpoint(str(config["endpoint"]))
    insecure = bool(config.get("insecure", False))
    with _client(insecure) as client:
        headers = auth_headers(client, auth_method, endpoint, config, secret)
        version = get_version(client, endpoint, headers)
        nodes = get_nodes(client, endpoint, headers)
    identity: dict[str, Any] = {
        "endpoint": endpoint,
        "principal": principal(auth_method, config),
        "version": version.get("version"),
        "release": version.get("release"),
        "repoid": version.get("repoid"),
        "insecure": insecure,
    }
    if nodes is not None:
        identity["nodes"] = len(nodes)
        identity["node_names"] = sorted(str(node["node"]) for node in nodes if node.get("node"))
    release = f"Proxmox VE {identity['version']}" if identity.get("version") else "Proxmox VE"
    return VerifyResult(True, identity, f"authenticated to {release} as {identity['principal']}")


def terraform_env(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> ResolvedEnv:
    env: dict[str, str] = {
        "PROXMOX_VE_ENDPOINT": normalise_endpoint(str(config["endpoint"])) + "/",
        "PROXMOX_VE_INSECURE": "true" if config.get("insecure") else "false",
    }
    if auth_method == "api_token":
        env["PROXMOX_VE_API_TOKEN"] = api_token(str(config["token_id"]), str(secret["token_secret"]))
    elif auth_method == "password":
        env["PROXMOX_VE_USERNAME"] = str(config["username"])
        env["PROXMOX_VE_PASSWORD"] = str(secret["password"])
    else:
        raise ValueError(f"unsupported Proxmox VE auth method {auth_method!r}")
    return ResolvedEnv(env, None)
