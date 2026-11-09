"""AWS connections: STS verification, Terraform environment resolution and the IAM Identity
Center (SSO) device flow.

The functions that talk to the network are small and module-level (`get_caller_identity`,
`assume_role`, `assume_role_with_web_identity`, `sso_role_credentials`, `sso_register_client`,
`sso_start_device_authorization`, `sso_create_token`) so tests can replace them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import botocore.session
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError

from .models import DEFAULT_SESSION_NAME, ResolvedEnv, VerifyResult

SECRET_ENV_KEYS: tuple[str, ...] = ("AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
SSO_CLIENT_NAME = "vmware-migration-agent"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
_USER_AGENT = "vmware-migration-agent/connections"


# ── sessions and clients ──────────────────────────────────────────────────────


def _client_config() -> Config:
    return Config(user_agent_extra=_USER_AGENT, retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=10, read_timeout=30)


def _base_session(base_method: str, config: dict[str, Any], secret: dict[str, Any]) -> boto3.Session:
    region = config.get("region") or None
    if base_method == "access_keys":
        return boto3.Session(
            aws_access_key_id=config.get("access_key_id"), aws_secret_access_key=secret.get("secret_access_key"),
            aws_session_token=secret.get("session_token") or None, region_name=region,
        )
    if base_method == "profile":
        bsession = botocore.session.get_session()
        if config.get("shared_credentials_file"):
            bsession.set_config_variable("credentials_file", str(config["shared_credentials_file"]))
        if config.get("config_file"):
            bsession.set_config_variable("config_file", str(config["config_file"]))
        return boto3.Session(botocore_session=bsession, profile_name=config.get("profile"), region_name=region)
    if base_method == "environment":
        return boto3.Session(region_name=region)
    raise ValueError(f"unsupported base credentials {base_method!r}")


def _session_from_credentials(credentials: dict[str, Any], region: str | None) -> boto3.Session:
    return boto3.Session(
        aws_access_key_id=credentials["access_key_id"], aws_secret_access_key=credentials["secret_access_key"],
        aws_session_token=credentials.get("session_token") or None, region_name=region,
    )


def _client(session: boto3.Session, service: str, region: str | None, endpoint_url: str | None = None, *, unsigned: bool = False) -> Any:
    config = _client_config()
    if unsigned:
        config = config.merge(Config(signature_version=UNSIGNED))
    return session.client(service, region_name=region or None, endpoint_url=endpoint_url or None, config=config)


def _credentials_from_sts(payload: dict[str, Any]) -> dict[str, Any]:
    creds = payload.get("Credentials") or {}
    expiration = creds.get("Expiration")
    if isinstance(expiration, datetime):
        expiration = expiration.astimezone(timezone.utc).isoformat(timespec="seconds")
    return {
        "access_key_id": creds.get("AccessKeyId"), "secret_access_key": creds.get("SecretAccessKey"),
        "session_token": creds.get("SessionToken"), "expiration": expiration,
    }


# ── network calls (stubbed in tests) ──────────────────────────────────────────


def get_caller_identity(session: boto3.Session, *, region: str | None, endpoint_url: str | None) -> dict[str, Any]:
    response = _client(session, "sts", region, endpoint_url).get_caller_identity()
    return {"account": response.get("Account"), "arn": response.get("Arn"), "user_id": response.get("UserId")}


def assume_role(session: boto3.Session, *, region: str | None, endpoint_url: str | None, role_arn: str, session_name: str, external_id: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"RoleArn": role_arn, "RoleSessionName": session_name}
    if external_id:
        params["ExternalId"] = external_id
    return _credentials_from_sts(_client(session, "sts", region, endpoint_url).assume_role(**params))


def assume_role_with_web_identity(*, region: str | None, endpoint_url: str | None, role_arn: str, session_name: str, token: str) -> dict[str, Any]:
    client = _client(boto3.Session(region_name=region or None), "sts", region, endpoint_url, unsigned=True)
    return _credentials_from_sts(client.assume_role_with_web_identity(RoleArn=role_arn, RoleSessionName=session_name, WebIdentityToken=token))


def sso_role_credentials(*, sso_region: str, account_id: str, role_name: str, access_token: str) -> dict[str, Any]:
    client = _client(boto3.Session(region_name=sso_region), "sso", sso_region, None, unsigned=True)
    response = client.get_role_credentials(roleName=role_name, accountId=account_id, accessToken=access_token)
    creds = response.get("roleCredentials") or {}
    expiration = creds.get("expiration")
    if isinstance(expiration, (int, float)):  # epoch milliseconds
        expiration = datetime.fromtimestamp(expiration / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    return {
        "access_key_id": creds.get("accessKeyId"), "secret_access_key": creds.get("secretAccessKey"),
        "session_token": creds.get("sessionToken"), "expiration": expiration,
    }


def sso_register_client(*, sso_region: str) -> dict[str, Any]:
    client = _client(boto3.Session(region_name=sso_region), "sso-oidc", sso_region, None, unsigned=True)
    response = client.register_client(clientName=SSO_CLIENT_NAME, clientType="public")
    return {"client_id": response["clientId"], "client_secret": response["clientSecret"], "client_secret_expires_at": response.get("clientSecretExpiresAt")}


def sso_start_device_authorization(*, sso_region: str, client_id: str, client_secret: str, start_url: str) -> dict[str, Any]:
    client = _client(boto3.Session(region_name=sso_region), "sso-oidc", sso_region, None, unsigned=True)
    response = client.start_device_authorization(clientId=client_id, clientSecret=client_secret, startUrl=start_url)
    return {
        "device_code": response["deviceCode"], "user_code": response["userCode"], "verification_uri": response["verificationUri"],
        "verification_uri_complete": response.get("verificationUriComplete"), "expires_in": int(response.get("expiresIn") or 600),
        "interval": int(response.get("interval") or 5),
    }


def sso_create_token(*, sso_region: str, client_id: str, client_secret: str, device_code: str) -> dict[str, Any]:
    """Poll the token endpoint once. Returns {status: pending|slow_down|expired|denied|complete, ...}."""
    client = _client(boto3.Session(region_name=sso_region), "sso-oidc", sso_region, None, unsigned=True)
    try:
        response = client.create_token(clientId=client_id, clientSecret=client_secret, grantType=DEVICE_GRANT, deviceCode=device_code)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code") or "")
        if code == "AuthorizationPendingException":
            return {"status": "pending"}
        if code == "SlowDownException":
            return {"status": "slow_down"}
        if code == "ExpiredTokenException":
            return {"status": "expired"}
        if code in {"AccessDeniedException", "InvalidGrantException", "UnauthorizedClientException"}:
            return {"status": "denied", "message": str((exc.response.get("Error") or {}).get("Message") or code)}
        raise
    return {"status": "complete", "access_token": response["accessToken"], "expires_in": int(response.get("expiresIn") or 28800)}


# ── resolution ────────────────────────────────────────────────────────────────


def _sso_token(secret: dict[str, Any]) -> str:
    token = secret.get("sso_access_token")
    if not token:
        raise ValueError("not signed in: start the device-code flow to obtain an SSO session")
    expires = secret.get("sso_token_expires_at")
    if expires:
        try:
            expiry = datetime.fromisoformat(str(expires))
        except ValueError:
            expiry = None
        if expiry is not None and expiry <= datetime.now(timezone.utc):
            raise ValueError("the SSO session has expired; sign in again with the device-code flow")
    return str(token)


def resolve_session(auth_method: str, config: dict[str, Any], secret: dict[str, Any]) -> tuple[boto3.Session, dict[str, Any] | None]:
    """A boto3 session for the method and, for methods that mint temporary credentials, those credentials."""
    region = config.get("region") or None
    endpoint_url = config.get("endpoint_url") or None
    if auth_method in {"access_keys", "profile", "environment"}:
        return _base_session(auth_method, config, secret), None
    if auth_method == "assume_role":
        base = _base_session(str(config.get("base_method") or "access_keys"), config, secret)
        creds = assume_role(
            base, region=region, endpoint_url=endpoint_url, role_arn=str(config["role_arn"]),
            session_name=str(config.get("session_name") or DEFAULT_SESSION_NAME), external_id=config.get("external_id") or None,
        )
        return _session_from_credentials(creds, region), creds
    if auth_method == "web_identity":
        token = Path(str(config["web_identity_token_file"])).read_text(encoding="utf-8").strip()
        creds = assume_role_with_web_identity(
            region=region, endpoint_url=endpoint_url, role_arn=str(config["role_arn"]),
            session_name=str(config.get("session_name") or DEFAULT_SESSION_NAME), token=token,
        )
        return _session_from_credentials(creds, region), creds
    if auth_method == "sso":
        creds = sso_role_credentials(
            sso_region=str(config["sso_region"]), account_id=str(config["account_id"]), role_name=str(config["role_name"]),
            access_token=_sso_token(secret),
        )
        return _session_from_credentials(creds, region), creds
    raise ValueError(f"unsupported AWS auth method {auth_method!r}")


def verify(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> VerifyResult:
    session, creds = resolve_session(auth_method, config, secret)
    identity = get_caller_identity(session, region=config.get("region") or None, endpoint_url=config.get("endpoint_url") or None)
    if creds and creds.get("expiration"):
        identity["credentials_expire_at"] = creds["expiration"]
    identity["region"] = config.get("region")
    return VerifyResult(True, identity, f"authenticated as {identity.get('arn') or identity.get('account')}")


def terraform_env(auth_method: str, config: dict[str, Any], secret: dict[str, Any], *, connection_id: str) -> ResolvedEnv:
    region = str(config.get("region") or "")
    env: dict[str, str] = {}
    if region:
        env["AWS_REGION"] = region
        env["AWS_DEFAULT_REGION"] = region
    if config.get("endpoint_url"):
        env["AWS_ENDPOINT_URL"] = str(config["endpoint_url"])
    expires_at: str | None = None
    if auth_method == "access_keys":
        env["AWS_ACCESS_KEY_ID"] = str(config["access_key_id"])
        env["AWS_SECRET_ACCESS_KEY"] = str(secret["secret_access_key"])
        if secret.get("session_token"):
            env["AWS_SESSION_TOKEN"] = str(secret["session_token"])
    elif auth_method == "profile":
        env["AWS_PROFILE"] = str(config["profile"])
        env["AWS_SDK_LOAD_CONFIG"] = "1"
        if config.get("shared_credentials_file"):
            env["AWS_SHARED_CREDENTIALS_FILE"] = str(config["shared_credentials_file"])
        if config.get("config_file"):
            env["AWS_CONFIG_FILE"] = str(config["config_file"])
    elif auth_method == "environment":
        pass
    elif auth_method == "web_identity":
        env["AWS_ROLE_ARN"] = str(config["role_arn"])
        env["AWS_WEB_IDENTITY_TOKEN_FILE"] = str(config["web_identity_token_file"])
        env["AWS_ROLE_SESSION_NAME"] = str(config.get("session_name") or DEFAULT_SESSION_NAME)
    elif auth_method in {"assume_role", "sso"}:
        _session, creds = resolve_session(auth_method, config, secret)
        assert creds is not None
        env["AWS_ACCESS_KEY_ID"] = str(creds["access_key_id"])
        env["AWS_SECRET_ACCESS_KEY"] = str(creds["secret_access_key"])
        if creds.get("session_token"):
            env["AWS_SESSION_TOKEN"] = str(creds["session_token"])
        expires_at = creds.get("expiration")
    else:
        raise ValueError(f"unsupported AWS auth method {auth_method!r}")
    return ResolvedEnv(env, expires_at)


# ── device flow (IAM Identity Center) ─────────────────────────────────────────


def device_start(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Register a public client and start device authorization.

    Returns (public payload, flow secret to store encrypted, expires_at ISO).
    """
    sso_region = str(config["sso_region"])
    registration = sso_register_client(sso_region=sso_region)
    auth = sso_start_device_authorization(
        sso_region=sso_region, client_id=registration["client_id"], client_secret=registration["client_secret"], start_url=str(config["start_url"]),
    )
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(auth["expires_in"]))).isoformat(timespec="seconds")
    public = {
        "user_code": auth["user_code"], "verification_uri": auth["verification_uri"],
        "verification_uri_complete": auth.get("verification_uri_complete"), "expires_in": int(auth["expires_in"]), "interval": int(auth["interval"]),
    }
    flow_secret = {"client_id": registration["client_id"], "client_secret": registration["client_secret"], "device_code": auth["device_code"]}
    return public, flow_secret, expires_at


def device_poll(config: dict[str, Any], flow_secret: dict[str, Any]) -> dict[str, Any]:
    """One poll. On completion returns {status: complete, secret: {sso_access_token, sso_token_expires_at}}."""
    result = sso_create_token(
        sso_region=str(config["sso_region"]), client_id=str(flow_secret["client_id"]), client_secret=str(flow_secret["client_secret"]),
        device_code=str(flow_secret["device_code"]),
    )
    status = result.get("status")
    if status in {"pending", "slow_down"}:
        return {"status": "pending", "message": "waiting for the sign-in to be approved" if status == "pending" else "waiting (slow down polling)"}
    if status == "expired":
        return {"status": "expired", "message": "the device code expired; start again"}
    if status == "denied":
        return {"status": "error", "message": str(result.get("message") or "sign-in was denied")}
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(result.get("expires_in") or 28800))).isoformat(timespec="seconds")
    return {
        "status": "complete", "message": "signed in",
        "secret": {"sso_access_token": str(result["access_token"]), "sso_token_expires_at": expires_at},
    }
