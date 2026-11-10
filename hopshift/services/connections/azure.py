"""Azure connections: azure-identity credentials, ARM verification, Terraform `ARM_*` variables
and the device-code sign-in.

Device-code sign-in keeps the `DeviceCodeCredential` in memory (it holds the refresh token);
it is valid for the lifetime of the process and is never persisted.
"""
from __future__ import annotations

import base64
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from azure.identity import (
    AzureAuthorityHosts,
    AzureCliCredential,
    CertificateCredential,
    ClientAssertionCredential,
    ClientSecretCredential,
    DeviceCodeCredential,
    ManagedIdentityCredential,
    WorkloadIdentityCredential,
)

from .models import AZURE_CLI_PUBLIC_CLIENT_ID, ResolvedEnv, VerifyResult, safe_error

SECRET_ENV_KEYS: tuple[str, ...] = ("ARM_CLIENT_SECRET", "ARM_CLIENT_CERTIFICATE", "ARM_CLIENT_CERTIFICATE_PASSWORD", "ARM_OIDC_TOKEN")
ARM_API_VERSION = "2022-12-01"
DEVICE_PROMPT_TIMEOUT = 30.0

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "public": {"authority": AzureAuthorityHosts.AZURE_PUBLIC_CLOUD, "arm": "https://management.azure.com"},
    "usgovernment": {"authority": AzureAuthorityHosts.AZURE_GOVERNMENT, "arm": "https://management.usgovernmentcloudapi.net"},
    "china": {"authority": AzureAuthorityHosts.AZURE_CHINA, "arm": "https://management.chinacloudapi.cn"},
}


def environment(config: dict[str, Any]) -> tuple[str, dict[str, str]]:
    name = str(config.get("environment") or "public")
    settings = ENVIRONMENTS.get(name)
    if settings is None:
        raise ValueError(f"unknown Azure environment {name!r}")
    return name, settings


def _scope(arm: str) -> str:
    return f"{arm}/.default"


def _certificate_bytes(secret: dict[str, Any]) -> bytes:
    """PEM text is used as-is; anything else is treated as a base64-encoded PFX."""
    text = str(secret.get("certificate_pem") or "")
    if "-----BEGIN" in text:
        return text.encode("utf-8")
    return base64.b64decode("".join(text.split()))


def _certificate_b64(secret: dict[str, Any]) -> str:
    """What `ARM_CLIENT_CERTIFICATE` expects: base64 of the PEM (or the PFX as pasted)."""
    text = str(secret.get("certificate_pem") or "")
    if "-----BEGIN" in text:
        return base64.b64encode(text.encode("utf-8")).decode("ascii")
    return "".join(text.split())


# ── device sessions (in memory) ───────────────────────────────────────────────


class DeviceSession:
    def __init__(self, flow_id: str, connection_id: str, scope: str) -> None:
        self.flow_id = flow_id
        self.connection_id = connection_id
        self.scope = scope
        self.credential: Any = None
        self.ready = threading.Event()
        self.done = threading.Event()
        self.user_code: str | None = None
        self.verification_uri: str | None = None
        self.expires_on: datetime | None = None
        self.error: str | None = None
        self.authenticated = False

    def prompt(self, verification_uri: str, user_code: str, expires_on: datetime) -> None:
        self.verification_uri, self.user_code, self.expires_on = verification_uri, user_code, expires_on
        self.ready.set()

    def run(self) -> None:
        try:
            authenticate(self.credential, self.scope)
            self.authenticated = True
        except Exception as exc:  # noqa: BLE001 - reported to the poller, never raised in the thread
            self.error = safe_error(exc)
        finally:
            self.done.set()
            self.ready.set()


_SESSIONS: dict[str, DeviceSession] = {}
_SESSIONS_LOCK = threading.Lock()


def device_session(connection_id: str) -> DeviceSession | None:
    with _SESSIONS_LOCK:
        return _SESSIONS.get(connection_id)


def forget_device_session(connection_id: str) -> None:
    with _SESSIONS_LOCK:
        _SESSIONS.pop(connection_id, None)


# ── credentials (stubbed in tests) ────────────────────────────────────────────


def new_device_credential(*, client_id: str, tenant_id: str, authority: str, prompt_callback: Any) -> Any:
    return DeviceCodeCredential(
        client_id=client_id, tenant_id=tenant_id, authority=authority, prompt_callback=prompt_callback,
        disable_automatic_authentication=True, timeout=900,
    )


def authenticate(credential: Any, scope: str) -> Any:
    return credential.authenticate(scopes=[scope])


def build_credential(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> Any:
    _name, settings = environment(config)
    authority = settings["authority"]
    tenant_id = str(config["tenant_id"])
    if auth_method == "service_principal_secret":
        return ClientSecretCredential(tenant_id=tenant_id, client_id=str(config["client_id"]), client_secret=str(secret["client_secret"]), authority=authority)
    if auth_method == "service_principal_certificate":
        password = secret.get("certificate_password")
        return CertificateCredential(
            tenant_id=tenant_id, client_id=str(config["client_id"]), certificate_data=_certificate_bytes(secret),
            password=str(password).encode("utf-8") if password else None, authority=authority,
        )
    if auth_method == "managed_identity":
        return ManagedIdentityCredential(client_id=str(config["client_id"])) if config.get("client_id") else ManagedIdentityCredential()
    if auth_method == "oidc":
        if secret.get("oidc_token"):
            token = str(secret["oidc_token"])
            return ClientAssertionCredential(tenant_id=tenant_id, client_id=str(config["client_id"]), func=lambda: token, authority=authority)
        return WorkloadIdentityCredential(tenant_id=tenant_id, client_id=str(config["client_id"]), token_file_path=str(config["oidc_token_file_path"]), authority=authority)
    if auth_method == "cli":
        return AzureCliCredential(tenant_id=tenant_id)
    if auth_method == "device_code":
        session = device_session(connection_id)
        if session is None or not session.authenticated or session.credential is None:
            raise ValueError("not signed in: start the device-code flow first (sign-in lasts for the lifetime of the process)")
        return session.credential
    raise ValueError(f"unsupported Azure auth method {auth_method!r}")


# ── network calls (stubbed in tests) ──────────────────────────────────────────


def get_token(credential: Any, scope: str) -> str:
    return str(credential.get_token(scope).token)


def get_subscription(arm: str, token: str, subscription_id: str) -> dict[str, Any]:
    url = f"{arm}/subscriptions/{subscription_id}"
    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params={"api-version": ARM_API_VERSION}, headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 404:
        raise RuntimeError(f"subscription {subscription_id} was not found or the principal has no access to it")
    response.raise_for_status()
    body = response.json()
    return {"subscription_id": body.get("subscriptionId"), "subscription_name": body.get("displayName"), "tenant_id": body.get("tenantId"), "state": body.get("state")}


# ── service entry points ──────────────────────────────────────────────────────


def verify(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> VerifyResult:
    name, settings = environment(config)
    credential = build_credential(auth_method, config, secret, connection_id=connection_id)
    token = get_token(credential, _scope(settings["arm"]))
    identity = get_subscription(settings["arm"], token, str(config["subscription_id"]))
    identity["environment"] = name
    if config.get("client_id"):
        identity["client_id"] = config["client_id"]
    return VerifyResult(True, identity, f"authenticated to subscription {identity.get('subscription_name') or identity.get('subscription_id')}")


def terraform_env(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> ResolvedEnv:
    name, _settings = environment(config)
    env: dict[str, str] = {"ARM_SUBSCRIPTION_ID": str(config["subscription_id"]), "ARM_TENANT_ID": str(config["tenant_id"])}
    if name != "public":
        env["ARM_ENVIRONMENT"] = name
    if auth_method == "service_principal_secret":
        env["ARM_CLIENT_ID"] = str(config["client_id"])
        env["ARM_CLIENT_SECRET"] = str(secret["client_secret"])
    elif auth_method == "service_principal_certificate":
        env["ARM_CLIENT_ID"] = str(config["client_id"])
        env["ARM_CLIENT_CERTIFICATE"] = _certificate_b64(secret)
        if secret.get("certificate_password"):
            env["ARM_CLIENT_CERTIFICATE_PASSWORD"] = str(secret["certificate_password"])
    elif auth_method == "managed_identity":
        env["ARM_USE_MSI"] = "true"
        if config.get("client_id"):
            env["ARM_CLIENT_ID"] = str(config["client_id"])
    elif auth_method == "oidc":
        env["ARM_USE_OIDC"] = "true"
        env["ARM_CLIENT_ID"] = str(config["client_id"])
        if secret.get("oidc_token"):
            env["ARM_OIDC_TOKEN"] = str(secret["oidc_token"])
        else:
            env["ARM_OIDC_TOKEN_FILE_PATH"] = str(config["oidc_token_file_path"])
    elif auth_method == "cli":
        env["ARM_USE_CLI"] = "true"
    elif auth_method == "device_code":
        raise ValueError("device-code sign-in verifies access; Terraform needs a service principal, managed identity, workload identity or CLI login")
    else:
        raise ValueError(f"unsupported Azure auth method {auth_method!r}")
    return ResolvedEnv(env, None)


# ── device flow ───────────────────────────────────────────────────────────────


def device_start(config: dict[str, Any], *, connection_id: str, flow_id: str, timeout: float = DEVICE_PROMPT_TIMEOUT) -> tuple[dict[str, Any], str]:
    """Start a device-code sign-in in a background thread; returns (public payload, expires_at ISO)."""
    _name, settings = environment(config)
    session = DeviceSession(flow_id, connection_id, _scope(settings["arm"]))
    session.credential = new_device_credential(
        client_id=str(config.get("client_id") or AZURE_CLI_PUBLIC_CLIENT_ID), tenant_id=str(config["tenant_id"]),
        authority=settings["authority"], prompt_callback=session.prompt,
    )
    with _SESSIONS_LOCK:
        _SESSIONS[connection_id] = session
    thread = threading.Thread(target=session.run, name=f"azure-device-{flow_id[:8]}", daemon=True)
    thread.start()
    if not session.ready.wait(timeout):
        forget_device_session(connection_id)
        raise RuntimeError("timed out waiting for the device code from Microsoft Entra ID")
    if session.error and not session.user_code:
        forget_device_session(connection_id)
        raise RuntimeError(session.error)
    expires_on = session.expires_on or datetime.now(timezone.utc)
    if expires_on.tzinfo is None:
        expires_on = expires_on.replace(tzinfo=timezone.utc)
    expires_in = max(0, int((expires_on - datetime.now(timezone.utc)).total_seconds()))
    public = {
        "user_code": session.user_code, "verification_uri": session.verification_uri, "verification_uri_complete": None,
        "expires_in": expires_in, "interval": 5,
    }
    return public, expires_on.astimezone(timezone.utc).isoformat(timespec="seconds")


def device_poll(*, connection_id: str, flow_id: str) -> dict[str, Any]:
    session = device_session(connection_id)
    if session is None or session.flow_id != flow_id:
        return {"status": "error", "message": "the sign-in state is not available in this process; start again"}
    if not session.done.is_set():
        return {"status": "pending", "message": "waiting for the sign-in to complete"}
    if session.error:
        return {"status": "error", "message": session.error}
    return {"status": "complete", "message": "signed in"}
