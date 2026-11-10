from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError

import hopshift.services.connections.aws as aws
import hopshift.services.connections.azure as azure
import hopshift.services.connections.gcp as gcp
import hopshift.services.connections.openstack as openstack
import hopshift.services.connections.proxmox as proxmox
from hopshift.services.connections import ConnectionService, build_connection_service
from hopshift.services.connections.models import CATALOG, FIELD_TYPES
from hopshift.services.errors import Conflict, Invalid, NotFound, Unavailable
from hopshift.services.platform import Platform
from hopshift.services.secrets import SecretBox

AWS_KEYS = {"access_key_id": "AKIAEXAMPLEKEY", "region": "eu-west-1"}
AWS_SECRET = {"secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCy"}
IDENTITY = {"account": "123456789012", "arn": "arn:aws:iam::123456789012:user/migrator", "user_id": "AIDAEXAMPLE"}


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Platform:
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", SecretBox.generate_key())
    return Platform.from_config({"runtime": {"platform_db": str(tmp_path / "platform.sqlite")}})


@pytest.fixture
def service(platform: Platform) -> ConnectionService:
    assert isinstance(platform.connections, ConnectionService)
    return platform.connections


@pytest.fixture(autouse=True)
def _no_azure_sessions() -> Any:
    yield
    azure._SESSIONS.clear()


def _stub_identity(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]] | None = None) -> None:
    def fake(session: Any, *, region: str | None, endpoint_url: str | None) -> dict[str, Any]:
        if calls is not None:
            calls.append({"region": region, "endpoint_url": endpoint_url, "session": session})
        return dict(IDENTITY)

    monkeypatch.setattr(aws, "get_caller_identity", fake)


def _actions(platform: Platform) -> list[str]:
    entries, _total = platform.audit.list(limit=100)
    return [entry.action for entry in entries]


# ── catalog ───────────────────────────────────────────────────────────────────


def test_catalog_describes_every_provider_and_method(service: ConnectionService) -> None:
    catalog = service.catalog()
    assert set(catalog) == {"aws", "azure", "gcp", "openstack", "proxmox"}
    assert [m["key"] for m in catalog["aws"]["methods"]] == ["access_keys", "profile", "assume_role", "environment", "sso", "web_identity"]
    assert [m["key"] for m in catalog["azure"]["methods"]] == ["service_principal_secret", "service_principal_certificate", "managed_identity", "oidc", "cli", "device_code"]
    assert [m["key"] for m in catalog["gcp"]["methods"]] == ["service_account_key", "adc", "impersonation", "workload_identity_federation"]
    assert [m["key"] for m in catalog["openstack"]["methods"]] == ["password", "application_credential", "clouds_yaml"]
    assert [m["key"] for m in catalog["proxmox"]["methods"]] == ["api_token", "password"]
    for provider in catalog.values():
        assert provider["label"]
        for method in provider["methods"]:
            assert {"key", "label", "description", "terraform_ready", "fields"} <= set(method)
            for field in method["fields"]:
                assert {"key", "label", "type", "required", "secret", "help"} <= set(field)
                assert field["type"] in FIELD_TYPES
                if field["type"] == "select":
                    assert field["options"] and all({"value", "label"} <= set(option) for option in field["options"])
    device_code = next(m for m in catalog["azure"]["methods"] if m["key"] == "device_code")
    assert device_code["terraform_ready"] is False
    access_keys = next(m for m in catalog["aws"]["methods"] if m["key"] == "access_keys")
    secret_fields = {f["key"] for f in access_keys["fields"] if f["secret"]}
    assert secret_fields == {"secret_access_key", "session_token"}
    assert next(f for f in access_keys["fields"] if f["key"] == "secret_access_key")["type"] == "password"
    assume_role = CATALOG["aws"].method("assume_role")
    assert assume_role is not None and assume_role.field("session_name").default == "hopshift"


# ── create / validate / to_public ────────────────────────────────────────────


def test_create_validates_encrypts_and_never_exposes_secrets(platform: Platform, service: ConnectionService) -> None:
    connection = service.create(name=" Lab ", provider="aws", auth_method="access_keys", config=AWS_KEYS, secret=AWS_SECRET, actor="alice")
    assert connection.name == "Lab" and connection.status == "unverified" and connection.created_by == "alice"
    assert connection.secret_token and AWS_SECRET["secret_access_key"] not in connection.secret_token
    with platform.db.connect() as conn:
        row = conn.execute("SELECT config, secret_token, secret_keys FROM connections WHERE id = ?", (connection.id,)).fetchone()
    assert AWS_SECRET["secret_access_key"] not in row["config"] + row["secret_token"] + row["secret_keys"]
    assert platform.secrets.decrypt_json(row["secret_token"]) == AWS_SECRET

    public = service.to_public(connection)
    assert public["has_secret"] is True and public["secret_fields"] == ["secret_access_key"] and public["terraform_ready"] is True
    assert public["config"] == AWS_KEYS and AWS_SECRET["secret_access_key"] not in json.dumps(public)
    assert "secret_token" not in public and "secret" not in public

    assert service.get(connection.id).id == connection.id
    assert [item.id for item in service.list()] == [connection.id]
    assert _actions(platform) == ["connection.created"]
    entries, _ = platform.audit.list()
    assert AWS_SECRET["secret_access_key"] not in json.dumps(entries[0].details)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"provider": "digitalocean", "auth_method": "token", "config": {}, "secret": {}}, "unknown provider"),
        ({"provider": "aws", "auth_method": "magic", "config": {}, "secret": {}}, "unknown auth method"),
        ({"provider": "aws", "auth_method": "access_keys", "config": {**AWS_KEYS, "bogus": 1}, "secret": AWS_SECRET}, "unknown field 'bogus'"),
        ({"provider": "aws", "auth_method": "access_keys", "config": {"region": "eu-west-1"}, "secret": AWS_SECRET}, "access_key_id is required"),
        ({"provider": "aws", "auth_method": "access_keys", "config": {**AWS_KEYS, "secret_access_key": "x"}, "secret": {}}, "is secret; send it in `secret`"),
        ({"provider": "aws", "auth_method": "access_keys", "config": AWS_KEYS, "secret": {"region": "x"}}, "not a secret field"),
        ({"provider": "aws", "auth_method": "assume_role", "config": {"role_arn": "arn:aws:iam::1:role/r", "region": "eu-west-1"}, "secret": {}}, "access_key_id is required when base_method is access_keys"),
        ({"provider": "aws", "auth_method": "sso", "config": {"start_url": "https://x.awsapps.com/start", "sso_region": "eu-west-1", "account_id": "1", "role_name": "r", "region": "eu-west-1"}, "secret": {"sso_access_token": "t"}}, "managed by the device-code flow"),
        ({"provider": "azure", "auth_method": "oidc", "config": {"subscription_id": "s", "tenant_id": "t", "client_id": "c"}, "secret": {}}, "one of oidc_token or oidc_token_file_path"),
        ({"provider": "azure", "auth_method": "cli", "config": {"subscription_id": "s", "tenant_id": "t", "environment": "mars"}, "secret": {}}, "environment must be one of"),
        ({"provider": "gcp", "auth_method": "service_account_key", "config": {"project_id": "p"}, "secret": {"key_json": "{not json"}}, "key_json is not valid JSON"),
        ({"provider": "proxmox", "auth_method": "api_token", "config": {"endpoint": "pve.example.internal:8006", "token_id": "terraform@pve!hopshift"}, "secret": {"token_secret": "s"}}, "endpoint must be an http"),
        ({"provider": "proxmox", "auth_method": "api_token", "config": {"endpoint": "https://pve:8006", "token_id": "terraform"}, "secret": {"token_secret": "s"}}, "token_id must look like user@realm!tokenname"),
        ({"provider": "proxmox", "auth_method": "password", "config": {"endpoint": "https://pve:8006", "username": "root"}, "secret": {"password": "s"}}, "username must include the realm"),
        ({"provider": "proxmox", "auth_method": "password", "config": {"endpoint": "https://pve:8006", "username": "root@pam", "insecure": "maybe"}, "secret": {"password": "s"}}, "insecure must be a boolean"),
    ],
)
def test_create_rejects_invalid_input(service: ConnectionService, kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(Invalid, match=match):
        service.create(name="bad", actor="alice", **kwargs)


def test_create_rejects_bad_names_and_duplicates(service: ConnectionService) -> None:
    service.create(name="prod", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    with pytest.raises(Conflict):
        service.create(name="PROD", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    with pytest.raises(Invalid, match="name must be"):
        service.create(name="   ", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    with pytest.raises(Invalid, match="name must be"):
        service.create(name="x" * 81, provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")


def test_secrets_require_an_encryption_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOPSHIFT_SECRET_KEY", raising=False)
    platform = Platform.from_config({"runtime": {"platform_db": str(tmp_path / "nokey.sqlite")}})
    service = build_connection_service(platform)
    with pytest.raises(Unavailable, match="HOPSHIFT_SECRET_KEY"):
        service.create(name="keys", provider="aws", auth_method="access_keys", config=AWS_KEYS, secret=AWS_SECRET, actor="alice")
    # methods without secret fields still work without a key
    connection = service.create(name="env", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    assert connection.secret_token is None and service.to_public(connection)["has_secret"] is False
    assert service.terraform_env(connection.id) == {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"}
    assert service.secret_values(connection.id) == []
    with pytest.raises(Unavailable, match="HOPSHIFT_SECRET_KEY"):
        service.device_start(_sso(service).id, actor="alice")


# ── update / delete ───────────────────────────────────────────────────────────


def test_update_merges_secret_and_resets_status(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_identity(monkeypatch)
    connection = service.create(name="lab", provider="aws", auth_method="access_keys", config=AWS_KEYS, secret=AWS_SECRET, actor="alice")
    assert service.test(connection.id, actor="bob")["ok"] is True
    assert service.get(connection.id).status == "ok"

    renamed = service.update(connection.id, name="lab-2", actor="alice")
    assert renamed.name == "lab-2" and renamed.status == "ok"  # a rename alone keeps the verification

    updated = service.update(connection.id, secret={"session_token": "FwoGZXIvYXdzEBYaDExample"}, actor="alice")
    assert updated.status == "unverified" and updated.secret_keys == ["secret_access_key", "session_token"]
    assert platform.secrets.decrypt_json(updated.secret_token or "") == {**AWS_SECRET, "session_token": "FwoGZXIvYXdzEBYaDExample"}
    env = service.terraform_env(connection.id)
    assert env["AWS_SESSION_TOKEN"] == "FwoGZXIvYXdzEBYaDExample" and env["AWS_SECRET_ACCESS_KEY"] == AWS_SECRET["secret_access_key"]

    removed = service.update(connection.id, secret={"session_token": None}, actor="alice")
    assert removed.secret_keys == ["secret_access_key"]

    reconfigured = service.update(connection.id, config={"region": "us-west-2"}, actor="alice")
    assert reconfigured.config == {**AWS_KEYS, "region": "us-west-2"} and reconfigured.status == "unverified"
    with pytest.raises(Invalid, match="unknown field"):
        service.update(connection.id, config={"nope": "x"}, actor="alice")
    with pytest.raises(Invalid, match="secret_access_key is required"):
        service.update(connection.id, secret={"secret_access_key": None}, actor="alice")

    other = service.create(name="other", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    with pytest.raises(Conflict):
        service.update(other.id, name="LAB-2", actor="alice")
    assert _actions(platform).count("connection.updated") == 4
    entries, _ = platform.audit.list(action="connection.updated")
    assert entries[0].details["fields"] == ["config"] and entries[-1].details["fields"] == ["name"]
    assert "FwoGZXIvYXdzEBYaDExample" not in json.dumps([entry.details for entry in entries])


def test_delete_removes_connection_and_audits(platform: Platform, service: ConnectionService) -> None:
    connection = service.create(name="gone", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    service.delete(connection.id, actor="alice")
    with pytest.raises(NotFound):
        service.get(connection.id)
    with pytest.raises(NotFound):
        service.delete(connection.id, actor="alice")
    assert _actions(platform) == ["connection.deleted", "connection.created"]


# ── AWS ───────────────────────────────────────────────────────────────────────


def test_aws_access_keys_verify_env_and_masking(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _stub_identity(monkeypatch, calls)
    connection = service.create(
        name="localstack", provider="aws", auth_method="access_keys", config={**AWS_KEYS, "endpoint_url": "http://localhost:4566"},
        secret={**AWS_SECRET, "session_token": "SESSIONTOKENVALUE"}, actor="alice",
    )
    result = service.test(connection.id, actor="bob")
    assert result["ok"] is True and result["identity"]["account"] == "123456789012" and result["checked_at"]
    assert calls[0]["endpoint_url"] == "http://localhost:4566" and calls[0]["region"] == "eu-west-1"
    frozen = calls[0]["session"].get_credentials().get_frozen_credentials()
    assert frozen.access_key == AWS_KEYS["access_key_id"] and frozen.secret_key == AWS_SECRET["secret_access_key"] and frozen.token == "SESSIONTOKENVALUE"

    stored = service.get(connection.id)
    assert stored.status == "ok" and stored.last_checked_at == result["checked_at"]
    assert stored.last_check == {"identity": {**IDENTITY, "region": "eu-west-1"}, "message": "authenticated as arn:aws:iam::123456789012:user/migrator"}
    entries, _ = platform.audit.list(action="connection.tested")
    assert entries[0].outcome == "success" and entries[0].actor == "bob" and entries[0].target_id == connection.id

    assert service.terraform_env(connection.id) == {
        "AWS_REGION": "eu-west-1", "AWS_DEFAULT_REGION": "eu-west-1", "AWS_ENDPOINT_URL": "http://localhost:4566",
        "AWS_ACCESS_KEY_ID": AWS_KEYS["access_key_id"], "AWS_SECRET_ACCESS_KEY": AWS_SECRET["secret_access_key"], "AWS_SESSION_TOKEN": "SESSIONTOKENVALUE",
    }
    assert set(service.secret_values(connection.id)) == {AWS_SECRET["secret_access_key"], "SESSIONTOKENVALUE"}


def test_aws_verify_failure_is_short_and_masked(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(session: Any, *, region: str | None, endpoint_url: str | None) -> dict[str, Any]:
        raise ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": f"The security token {AWS_SECRET['secret_access_key']} is invalid.\nmore lines"}},
            "GetCallerIdentity",
        )

    monkeypatch.setattr(aws, "get_caller_identity", boom)
    connection = service.create(name="broken", provider="aws", auth_method="access_keys", config=AWS_KEYS, secret=AWS_SECRET, actor="alice")
    result = service.test(connection.id, actor="bob")
    assert result["ok"] is False and result["identity"] == {}
    assert result["message"] == "InvalidClientTokenId: The security token *** is invalid. more lines"
    assert service.get(connection.id).status == "failed"
    entries, _ = platform.audit.list(action="connection.tested")
    assert entries[0].outcome == "failure" and AWS_SECRET["secret_access_key"] not in json.dumps(entries[0].details)


def test_aws_profile_environment_and_web_identity_env(service: ConnectionService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = service.create(
        name="profile", provider="aws", auth_method="profile",
        config={"profile": "migration", "region": "eu-central-1", "shared_credentials_file": "/home/vma/.aws/credentials"}, secret={}, actor="alice",
    )
    assert service.terraform_env(profile.id) == {
        "AWS_REGION": "eu-central-1", "AWS_DEFAULT_REGION": "eu-central-1", "AWS_PROFILE": "migration", "AWS_SDK_LOAD_CONFIG": "1",
        "AWS_SHARED_CREDENTIALS_FILE": "/home/vma/.aws/credentials",
    }
    env_only = service.create(name="env", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    assert service.terraform_env(env_only.id) == {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"}

    token_file = tmp_path / "token"
    token_file.write_text("eyJhbGciOi.web.identity\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    def fake_web_identity(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"access_key_id": "ASIAWEB", "secret_access_key": "websecret", "session_token": "webtoken", "expiration": None}

    monkeypatch.setattr(aws, "assume_role_with_web_identity", fake_web_identity)
    _stub_identity(monkeypatch)
    web = service.create(
        name="irsa", provider="aws", auth_method="web_identity",
        config={"role_arn": "arn:aws:iam::123456789012:role/irsa", "web_identity_token_file": str(token_file), "region": "us-east-1"}, secret={}, actor="alice",
    )
    assert service.test(web.id)["ok"] is True
    assert seen["token"] == "eyJhbGciOi.web.identity" and seen["session_name"] == "hopshift"
    assert service.terraform_env(web.id) == {
        "AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1", "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/irsa",
        "AWS_WEB_IDENTITY_TOKEN_FILE": str(token_file), "AWS_ROLE_SESSION_NAME": "hopshift",
    }


def test_aws_assume_role_resolves_and_caches_temporary_credentials(service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_assume_role(session: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        frozen = session.get_credentials().get_frozen_credentials()
        assert frozen.access_key == AWS_KEYS["access_key_id"]
        return {
            "access_key_id": "ASIATEMP", "secret_access_key": "tempsecret", "session_token": "temptoken",
            "expiration": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds"),
        }

    monkeypatch.setattr(aws, "assume_role", fake_assume_role)
    _stub_identity(monkeypatch)
    connection = service.create(
        name="xacct", provider="aws", auth_method="assume_role",
        config={**AWS_KEYS, "role_arn": "arn:aws:iam::999999999999:role/migration", "external_id": "ext-1"}, secret=AWS_SECRET, actor="alice",
    )
    assert connection.config["base_method"] == "access_keys" and connection.config["session_name"] == "hopshift"
    result = service.test(connection.id)
    assert result["ok"] is True and result["identity"]["credentials_expire_at"]
    assert calls[0]["role_arn"] == "arn:aws:iam::999999999999:role/migration" and calls[0]["external_id"] == "ext-1"

    env = service.terraform_env(connection.id)
    assert env["AWS_ACCESS_KEY_ID"] == "ASIATEMP" and env["AWS_SECRET_ACCESS_KEY"] == "tempsecret" and env["AWS_SESSION_TOKEN"] == "temptoken"
    assert env["AWS_REGION"] == "eu-west-1"
    assert len(calls) == 2
    service.terraform_env(connection.id)
    assert len(calls) == 2  # cached until the temporary credentials near expiry
    assert {"tempsecret", "temptoken", AWS_SECRET["secret_access_key"]} <= set(service.secret_values(connection.id))
    assert len(calls) == 2

    service.update(connection.id, config={"external_id": "ext-2"}, actor="alice")
    service.terraform_env(connection.id)
    assert len(calls) == 3 and calls[2]["external_id"] == "ext-2"

    def failing(session: Any, **kwargs: Any) -> dict[str, Any]:
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "not authorized"}}, "AssumeRole")

    monkeypatch.setattr(aws, "assume_role", failing)
    service.update(connection.id, config={"external_id": None}, actor="alice")
    with pytest.raises(Unavailable, match="AccessDenied: not authorized"):
        service.terraform_env(connection.id)
    assert set(service.secret_values(connection.id)) == {AWS_SECRET["secret_access_key"]}


def _sso(service: ConnectionService) -> Any:
    return service.create(
        name="sso", provider="aws", auth_method="sso",
        config={"start_url": "https://acme.awsapps.com/start", "sso_region": "eu-west-1", "account_id": "123456789012", "role_name": "Migrator", "region": "eu-west-1"},
        secret={}, actor="alice",
    )


def test_aws_sso_device_flow(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    polls: list[str] = []
    token_results = iter([{"status": "pending"}, {"status": "slow_down"}, {"status": "complete", "access_token": "SSOACCESSTOKEN", "expires_in": 3600}])

    monkeypatch.setattr(aws, "sso_register_client", lambda *, sso_region: {"client_id": "cid", "client_secret": "csecret", "client_secret_expires_at": 0})
    monkeypatch.setattr(aws, "sso_start_device_authorization", lambda **kw: {
        "device_code": "DEVCODE", "user_code": "ABCD-EFGH", "verification_uri": "https://device.sso.eu-west-1.amazonaws.com/",
        "verification_uri_complete": "https://device.sso.eu-west-1.amazonaws.com/?user_code=ABCD-EFGH", "expires_in": 600, "interval": 1,
    })

    def fake_create_token(**kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"sso_region": "eu-west-1", "client_id": "cid", "client_secret": "csecret", "device_code": "DEVCODE"}
        polls.append("poll")
        return next(token_results)

    def fake_role_credentials(**kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"sso_region": "eu-west-1", "account_id": "123456789012", "role_name": "Migrator", "access_token": "SSOACCESSTOKEN"}
        return {"access_key_id": "ASIASSO", "secret_access_key": "ssosecret", "session_token": "ssotoken", "expiration": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}

    monkeypatch.setattr(aws, "sso_create_token", fake_create_token)
    monkeypatch.setattr(aws, "sso_role_credentials", fake_role_credentials)
    _stub_identity(monkeypatch)

    connection = _sso(service)
    assert service.test(connection.id)["message"].startswith("not signed in")
    with pytest.raises(Invalid, match="not signed in"):
        service.terraform_env(connection.id)

    started = service.device_start(connection.id, actor="alice")
    assert started["user_code"] == "ABCD-EFGH" and started["verification_uri_complete"].endswith("ABCD-EFGH") and started["interval"] == 1
    flow = service.store.get_flow(started["flow_id"])
    assert flow.status == "pending" and "csecret" not in json.dumps(flow.payload) and flow.secret_token
    assert platform.secrets.decrypt_json(flow.secret_token)["device_code"] == "DEVCODE"

    assert service.device_poll(connection.id, started["flow_id"])["status"] == "pending"
    assert service.device_poll(connection.id, started["flow_id"])["status"] == "pending"
    done = service.device_poll(connection.id, started["flow_id"], actor="alice")
    assert done == {"status": "complete", "message": "authenticated as arn:aws:iam::123456789012:user/migrator"}
    assert polls == ["poll"] * 3

    stored = service.get(connection.id)
    assert stored.status == "ok" and stored.secret_keys == ["sso_access_token", "sso_token_expires_at"]
    assert platform.secrets.decrypt_json(stored.secret_token or "")["sso_access_token"] == "SSOACCESSTOKEN"
    flow = service.store.get_flow(started["flow_id"])
    assert flow.status == "complete" and flow.secret_token is None
    assert service.device_poll(connection.id, started["flow_id"]) == {"status": "complete", "message": "signed in"}

    env = service.terraform_env(connection.id)
    assert env["AWS_ACCESS_KEY_ID"] == "ASIASSO" and env["AWS_SESSION_TOKEN"] == "ssotoken"
    assert {"SSOACCESSTOKEN", "ssosecret", "ssotoken"} <= set(service.secret_values(connection.id))
    assert "connection.device_started" in _actions(platform) and "connection.device_completed" in _actions(platform)

    with pytest.raises(NotFound):
        service.device_poll(connection.id, "nope")
    other = service.create(name="env", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    with pytest.raises(Invalid, match="does not use a device flow"):
        service.device_start(other.id)
    with pytest.raises(NotFound):
        service.device_poll(other.id, started["flow_id"])


def test_aws_sso_device_flow_expiry_and_denial(service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws, "sso_register_client", lambda *, sso_region: {"client_id": "cid", "client_secret": "csecret", "client_secret_expires_at": 0})
    monkeypatch.setattr(aws, "sso_start_device_authorization", lambda **kw: {
        "device_code": "DEVCODE", "user_code": "ABCD-EFGH", "verification_uri": "https://device.sso.eu-west-1.amazonaws.com/",
        "verification_uri_complete": None, "expires_in": 600, "interval": 5,
    })
    monkeypatch.setattr(aws, "sso_create_token", lambda **kw: {"status": "denied", "message": "User denied the request"})
    connection = _sso(service)
    started = service.device_start(connection.id)
    polled = service.device_poll(connection.id, started["flow_id"])
    assert polled["status"] == "error" and "last check" in polled["message"]  # generic over HTTP
    assert service.get(connection.id).last_check["message"] == "User denied the request"  # detail kept on the connection
    assert service.store.get_flow(started["flow_id"]).status == "error"

    monkeypatch.setattr(aws, "sso_create_token", lambda **kw: {"status": "expired"})
    started = service.device_start(connection.id)
    assert service.device_poll(connection.id, started["flow_id"])["status"] == "expired"

    monkeypatch.setattr(aws, "sso_start_device_authorization", lambda **kw: {
        "device_code": "DEVCODE", "user_code": "ABCD-EFGH", "verification_uri": "https://x", "verification_uri_complete": None, "expires_in": -1, "interval": 5,
    })
    started = service.device_start(connection.id)
    assert service.device_poll(connection.id, started["flow_id"])["status"] == "expired"
    assert service.get(connection.id).status == "unverified"


def test_aws_sso_create_token_maps_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, code: str | None) -> None:
            self.code = code

        def create_token(self, **kwargs: Any) -> dict[str, Any]:
            if self.code:
                raise ClientError({"Error": {"Code": self.code, "Message": "m"}}, "CreateToken")
            return {"accessToken": "tok", "expiresIn": 10}

    for code, expected in [("AuthorizationPendingException", "pending"), ("SlowDownException", "slow_down"), ("ExpiredTokenException", "expired"), ("AccessDeniedException", "denied"), (None, "complete")]:
        monkeypatch.setattr(aws, "_client", lambda *a, code=code, **k: FakeClient(code))
        assert aws.sso_create_token(sso_region="eu-west-1", client_id="c", client_secret="s", device_code="d")["status"] == expected
    monkeypatch.setattr(aws, "_client", lambda *a, **k: FakeClient("InternalServerException"))
    with pytest.raises(ClientError):
        aws.sso_create_token(sso_region="eu-west-1", client_id="c", client_secret="s", device_code="d")


# ── Azure ─────────────────────────────────────────────────────────────────────

AZURE = {"subscription_id": "11111111-1111-1111-1111-111111111111", "tenant_id": "22222222-2222-2222-2222-222222222222"}
SUBSCRIPTION = {"subscription_id": AZURE["subscription_id"], "subscription_name": "Landing zone", "tenant_id": AZURE["tenant_id"], "state": "Enabled"}


def test_azure_service_principal_verify_and_env(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_token(credential: Any, scope: str) -> str:
        seen["credential"] = credential
        seen["scope"] = scope
        return "eyJ.arm.token"

    def fake_subscription(arm: str, token: str, subscription_id: str) -> dict[str, Any]:
        seen.update({"arm": arm, "token": token, "subscription_id": subscription_id})
        return dict(SUBSCRIPTION)

    monkeypatch.setattr(azure, "get_token", fake_token)
    monkeypatch.setattr(azure, "get_subscription", fake_subscription)
    connection = service.create(
        name="sp", provider="azure", auth_method="service_principal_secret", config={**AZURE, "client_id": "33333333-3333-3333-3333-333333333333"},
        secret={"client_secret": "sp-secret-value"}, actor="alice",
    )
    assert connection.config["environment"] == "public"
    result = service.test(connection.id)
    assert result["ok"] is True and result["identity"]["subscription_name"] == "Landing zone" and result["identity"]["environment"] == "public"
    assert type(seen["credential"]).__name__ == "ClientSecretCredential" and seen["scope"] == "https://management.azure.com/.default"
    assert seen["arm"] == "https://management.azure.com" and seen["subscription_id"] == AZURE["subscription_id"]
    assert service.terraform_env(connection.id) == {
        "ARM_SUBSCRIPTION_ID": AZURE["subscription_id"], "ARM_TENANT_ID": AZURE["tenant_id"],
        "ARM_CLIENT_ID": "33333333-3333-3333-3333-333333333333", "ARM_CLIENT_SECRET": "sp-secret-value",
    }
    assert service.secret_values(connection.id) == ["sp-secret-value"]

    gov = service.create(name="gov", provider="azure", auth_method="cli", config={**AZURE, "environment": "usgovernment"}, secret={}, actor="alice")
    service.test(gov.id)
    assert seen["arm"] == "https://management.usgovernmentcloudapi.net" and seen["scope"] == "https://management.usgovernmentcloudapi.net/.default"
    assert service.terraform_env(gov.id) == {"ARM_SUBSCRIPTION_ID": AZURE["subscription_id"], "ARM_TENANT_ID": AZURE["tenant_id"], "ARM_ENVIRONMENT": "usgovernment", "ARM_USE_CLI": "true"}


def test_azure_remaining_methods_terraform_env(service: ConnectionService) -> None:
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----\n"
    cert = service.create(
        name="cert", provider="azure", auth_method="service_principal_certificate", config={**AZURE, "client_id": "c1"},
        secret={"certificate_pem": pem, "certificate_password": "pfxpass"}, actor="alice",
    )
    env = service.terraform_env(cert.id)
    import base64

    assert base64.b64decode(env["ARM_CLIENT_CERTIFICATE"]).decode() == pem.strip("\r\n") and env["ARM_CLIENT_CERTIFICATE_PASSWORD"] == "pfxpass"
    assert env["ARM_CLIENT_ID"] == "c1"
    assert {env["ARM_CLIENT_CERTIFICATE"], "pfxpass", pem.strip("\r\n")} <= set(service.secret_values(cert.id))

    msi = service.create(name="msi", provider="azure", auth_method="managed_identity", config={**AZURE, "client_id": "uami"}, secret={}, actor="alice")
    assert service.terraform_env(msi.id) == {"ARM_SUBSCRIPTION_ID": AZURE["subscription_id"], "ARM_TENANT_ID": AZURE["tenant_id"], "ARM_USE_MSI": "true", "ARM_CLIENT_ID": "uami"}
    system_msi = service.create(name="msi2", provider="azure", auth_method="managed_identity", config=AZURE, secret={}, actor="alice")
    assert "ARM_CLIENT_ID" not in service.terraform_env(system_msi.id)

    oidc_token = service.create(name="gha", provider="azure", auth_method="oidc", config={**AZURE, "client_id": "c2"}, secret={"oidc_token": "eyJ.oidc"}, actor="alice")
    assert service.terraform_env(oidc_token.id) == {"ARM_SUBSCRIPTION_ID": AZURE["subscription_id"], "ARM_TENANT_ID": AZURE["tenant_id"], "ARM_USE_OIDC": "true", "ARM_CLIENT_ID": "c2", "ARM_OIDC_TOKEN": "eyJ.oidc"}
    oidc_file = service.create(name="k8s", provider="azure", auth_method="oidc", config={**AZURE, "client_id": "c3", "oidc_token_file_path": "/var/run/secrets/azure/tokens/azure-identity-token"}, secret={}, actor="alice")
    assert service.terraform_env(oidc_file.id)["ARM_OIDC_TOKEN_FILE_PATH"] == "/var/run/secrets/azure/tokens/azure-identity-token"

    device = service.create(name="me", provider="azure", auth_method="device_code", config=AZURE, secret={}, actor="alice")
    assert service.to_public(device)["terraform_ready"] is False and device.config["client_id"] == "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
    with pytest.raises(Invalid, match="device-code sign-in verifies access; Terraform needs a service principal"):
        service.terraform_env(device.id)


class _FakeDeviceCredential:
    """Stands in for azure.identity.DeviceCodeCredential: prompts, then completes or fails."""

    def __init__(self, prompt_callback: Any, *, fail: str | None = None, hang: bool = False) -> None:
        self.prompt_callback = prompt_callback
        self.fail = fail
        self.hang = hang
        self.tokens = 0

    def authenticate(self, scopes: list[str]) -> Any:
        self.prompt_callback("https://microsoft.com/devicelogin", "WXYZ1234", datetime.now(timezone.utc) + timedelta(minutes=15))
        if self.hang:
            import threading

            threading.Event().wait(0.3)
        if self.fail:
            raise RuntimeError(self.fail)
        return object()

    def get_token(self, scope: str) -> Any:
        self.tokens += 1
        return type("Token", (), {"token": "device-token"})()


def test_azure_device_code_flow(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    built: dict[str, Any] = {}

    def fake_new_credential(**kwargs: Any) -> _FakeDeviceCredential:
        built.update({k: v for k, v in kwargs.items() if k != "prompt_callback"})
        return _FakeDeviceCredential(kwargs["prompt_callback"], hang=True)

    monkeypatch.setattr(azure, "new_device_credential", fake_new_credential)
    monkeypatch.setattr(azure, "get_subscription", lambda arm, token, subscription_id: dict(SUBSCRIPTION))
    connection = service.create(name="me", provider="azure", auth_method="device_code", config=AZURE, secret={}, actor="alice")
    assert service.test(connection.id)["message"].startswith("not signed in")

    started = service.device_start(connection.id, actor="alice")
    assert started["user_code"] == "WXYZ1234" and started["verification_uri"] == "https://microsoft.com/devicelogin" and started["expires_in"] > 800
    assert built == {"client_id": "04b07795-8ddb-461a-bbee-02f9e1bf7b46", "tenant_id": AZURE["tenant_id"], "authority": "login.microsoftonline.com"}
    assert service.device_poll(connection.id, started["flow_id"])["status"] == "pending"

    session = azure.device_session(connection.id)
    assert session is not None and session.done.wait(5)
    done = service.device_poll(connection.id, started["flow_id"], actor="alice")
    assert done["status"] == "complete" and "Landing zone" in done["message"]
    stored = service.get(connection.id)
    assert stored.status == "ok" and stored.secret_token is None  # nothing persisted: the credential lives in memory
    assert session.credential.tokens == 1
    assert service.test(connection.id)["ok"] is True and session.credential.tokens == 2

    service.delete(connection.id, actor="alice")
    assert azure.device_session(connection.id) is None


def test_azure_device_code_failures(service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(azure, "new_device_credential", lambda **kw: _FakeDeviceCredential(kw["prompt_callback"], fail="AADSTS70016: user declined"))
    connection = service.create(name="me", provider="azure", auth_method="device_code", config=AZURE, secret={}, actor="alice")
    started = service.device_start(connection.id)
    session = azure.device_session(connection.id)
    assert session is not None and session.done.wait(5)
    polled = service.device_poll(connection.id, started["flow_id"])
    assert polled["status"] == "error" and "last check" in polled["message"]
    assert service.get(connection.id).last_check["message"] == "AADSTS70016: user declined"
    assert service.get(connection.id).status == "unverified"

    # a flow from a previous process (no in-memory session) reports an error instead of hanging
    azure._SESSIONS.clear()
    monkeypatch.setattr(azure, "new_device_credential", lambda **kw: _FakeDeviceCredential(kw["prompt_callback"], hang=True))
    started = service.device_start(connection.id)
    azure._SESSIONS.clear()
    assert service.device_poll(connection.id, started["flow_id"])["status"] == "error"


# ── GCP ───────────────────────────────────────────────────────────────────────

KEY_JSON = json.dumps({"type": "service_account", "project_id": "demo", "client_email": "tf@demo.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", "token_uri": "https://oauth2.googleapis.com/token"})
WIF_JSON = json.dumps({"type": "external_account", "audience": "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/p/providers/x", "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request", "token_url": "https://sts.googleapis.com/v1/token", "credential_source": {"environment_id": "aws1", "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15"}})


def test_gcp_verify_and_env(service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    class Creds:
        token = "ya29.token"
        service_account_email = "tf@demo.iam.gserviceaccount.com"

    seen: dict[str, Any] = {}
    monkeypatch.setattr(gcp, "refresh_token", lambda credentials: credentials.token)

    def fake_project(token: str, project_id: str) -> dict[str, Any]:
        seen.update({"token": token, "project_id": project_id})
        return {"project_id": project_id, "project_name": "Demo", "project_number": "1234", "state": "ACTIVE"}

    monkeypatch.setattr(gcp, "get_project", fake_project)

    built: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def fake_build(auth_method: str, config: dict[str, Any], secret: dict[str, Any]) -> tuple[Any, str | None]:
        built.append((auth_method, config, secret))
        return Creds(), None

    monkeypatch.setattr(gcp, "build_credentials", fake_build)
    key = service.create(name="sa", provider="gcp", auth_method="service_account_key", config={"project_id": "demo", "region": "europe-west1", "zone": "europe-west1-b"}, secret={"key_json": KEY_JSON}, actor="alice")
    result = service.test(key.id)
    assert result["ok"] is True and result["identity"] == {"project_id": "demo", "project_name": "Demo", "project_number": "1234", "state": "ACTIVE", "principal": "tf@demo.iam.gserviceaccount.com"}
    assert seen == {"token": "ya29.token", "project_id": "demo"} and built[0][0] == "service_account_key"
    env = service.terraform_env(key.id)
    assert env["GOOGLE_PROJECT"] == "demo" and env["GOOGLE_REGION"] == "europe-west1" and env["GOOGLE_ZONE"] == "europe-west1-b"
    assert json.loads(env["GOOGLE_CREDENTIALS"]) == json.loads(KEY_JSON) and "\n" not in env["GOOGLE_CREDENTIALS"]
    assert env["GOOGLE_CREDENTIALS"] in service.secret_values(key.id)

    adc = service.create(name="adc", provider="gcp", auth_method="adc", config={"project_id": "demo", "credentials_file": "/home/vma/.config/gcloud/application_default_credentials.json"}, secret={}, actor="alice")
    assert service.terraform_env(adc.id) == {"GOOGLE_PROJECT": "demo", "GOOGLE_APPLICATION_CREDENTIALS": "/home/vma/.config/gcloud/application_default_credentials.json"}
    metadata = service.create(name="meta", provider="gcp", auth_method="adc", config={"project_id": "demo"}, secret={}, actor="alice")
    assert service.terraform_env(metadata.id) == {"GOOGLE_PROJECT": "demo"}

    imp = service.create(name="imp", provider="gcp", auth_method="impersonation", config={"project_id": "demo", "target_service_account": "tf@demo.iam.gserviceaccount.com"}, secret={}, actor="alice")
    assert imp.config["base_method"] == "adc"
    assert service.terraform_env(imp.id) == {"GOOGLE_PROJECT": "demo", "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "tf@demo.iam.gserviceaccount.com"}
    imp_key = service.create(name="impk", provider="gcp", auth_method="impersonation", config={"project_id": "demo", "target_service_account": "tf@demo.iam.gserviceaccount.com", "base_method": "service_account_key"}, secret={"key_json": KEY_JSON}, actor="alice")
    assert service.terraform_env(imp_key.id)["GOOGLE_CREDENTIALS"]

    wif = service.create(name="wif", provider="gcp", auth_method="workload_identity_federation", config={"project_id": "demo"}, secret={"credential_config_json": WIF_JSON}, actor="alice")
    assert json.loads(service.terraform_env(wif.id)["GOOGLE_CREDENTIALS"])["type"] == "external_account"


def test_gcp_build_credentials_uses_google_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    credentials, principal = gcp.build_credentials("service_account_key", {"project_id": "demo"}, {"key_json": _rsa_key_json()})
    assert principal == "tf@demo.iam.gserviceaccount.com" and credentials.service_account_email == principal

    imp, target = gcp.build_credentials("impersonation", {"project_id": "demo", "target_service_account": "x@demo.iam.gserviceaccount.com", "base_method": "service_account_key"}, {"key_json": _rsa_key_json()})
    assert target == "x@demo.iam.gserviceaccount.com" and type(imp).__module__.endswith("impersonated_credentials")

    with pytest.raises(ValueError):
        gcp.build_credentials("nope", {}, {})


def _rsa_key_json() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return json.dumps({
        "type": "service_account", "project_id": "demo", "private_key_id": "k1", "private_key": pem,
        "client_email": "tf@demo.iam.gserviceaccount.com", "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token",
    })


# ── OpenStack ─────────────────────────────────────────────────────────────────

KEYSTONE_TOKEN = {
    "project": {"id": "p123", "name": "migration", "domain": {"id": "default", "name": "Default"}},
    "user": {"id": "u1", "name": "alice", "domain": {"id": "default", "name": "Default"}},
    "catalog": [{"type": "compute"}, {"type": "network"}, {"type": "identity"}], "expires_at": "2030-01-01T00:00:00.000000Z",
}


def test_openstack_verify_and_env(service: ConnectionService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, dict[str, Any]]] = []

    def fake_keystone(auth_url: str, body: dict[str, Any]) -> dict[str, Any]:
        requests.append((auth_url, body))
        return dict(KEYSTONE_TOKEN)

    monkeypatch.setattr(openstack, "keystone_authenticate", fake_keystone)
    pw = service.create(
        name="os-pw", provider="openstack", auth_method="password",
        config={"auth_url": "https://keystone.example.com:5000/", "region_name": "RegionOne", "interface": "public", "username": "alice", "project_name": "migration"},
        secret={"password": "os-password-value"}, actor="alice",
    )
    assert pw.config["user_domain_name"] == "Default" and pw.config["project_domain_name"] == "Default"
    result = service.test(pw.id)
    assert result["ok"] is True and result["identity"]["project_name"] == "migration" and result["identity"]["services"] == 3 and result["identity"]["region"] == "RegionOne"
    assert requests[0][0] == "https://keystone.example.com:5000/v3"
    assert requests[0][1]["auth"]["identity"]["password"]["user"] == {"name": "alice", "domain": {"name": "Default"}, "password": "os-password-value"}
    assert requests[0][1]["auth"]["scope"] == {"project": {"name": "migration", "domain": {"name": "Default"}}}
    assert service.terraform_env(pw.id) == {
        "OS_AUTH_URL": "https://keystone.example.com:5000/v3", "OS_REGION_NAME": "RegionOne", "OS_INTERFACE": "public", "OS_USERNAME": "alice",
        "OS_PASSWORD": "os-password-value", "OS_PROJECT_NAME": "migration", "OS_USER_DOMAIN_NAME": "Default", "OS_PROJECT_DOMAIN_NAME": "Default", "OS_IDENTITY_API_VERSION": "3",
    }
    assert service.secret_values(pw.id) == ["os-password-value"]

    app = service.create(
        name="os-app", provider="openstack", auth_method="application_credential",
        config={"auth_url": "https://keystone.example.com:5000/v3", "application_credential_id": "acid"}, secret={"application_credential_secret": "acsecret"}, actor="alice",
    )
    service.test(app.id)
    assert requests[1][1] == {"auth": {"identity": {"methods": ["application_credential"], "application_credential": {"id": "acid", "secret": "acsecret"}}}}
    assert service.terraform_env(app.id) == {
        "OS_AUTH_URL": "https://keystone.example.com:5000/v3", "OS_AUTH_TYPE": "v3applicationcredential", "OS_APPLICATION_CREDENTIAL_ID": "acid",
        "OS_APPLICATION_CREDENTIAL_SECRET": "acsecret", "OS_IDENTITY_API_VERSION": "3",
    }

    clouds = tmp_path / "clouds.yaml"
    clouds.write_text(
        "clouds:\n  lab:\n    auth:\n      auth_url: https://lab.example.com:5000\n      username: bob\n      password: yaml-password\n"
        "      project_name: lab\n      user_domain_name: Default\n      project_domain_name: Default\n    region_name: RegionOne\n",
        encoding="utf-8",
    )
    yaml_conn = service.create(name="os-yaml", provider="openstack", auth_method="clouds_yaml", config={"cloud": "lab", "clouds_yaml_path": str(clouds)}, secret={}, actor="alice")
    assert service.test(yaml_conn.id)["ok"] is True
    assert requests[2][0] == "https://lab.example.com:5000/v3" and requests[2][1]["auth"]["identity"]["password"]["user"]["name"] == "bob"
    assert service.terraform_env(yaml_conn.id) == {"OS_CLOUD": "lab", "OS_CLIENT_CONFIG_FILE": str(clouds)}
    assert service.secret_values(yaml_conn.id) == ["yaml-password"]

    missing = service.create(name="os-missing", provider="openstack", auth_method="clouds_yaml", config={"cloud": "nope", "clouds_yaml_path": str(clouds)}, secret={}, actor="alice")
    failed = service.test(missing.id)
    assert failed["ok"] is False and "cloud 'nope' is not defined" in failed["message"]


# ── Proxmox VE ────────────────────────────────────────────────────────────────

PVE_TOKEN_SECRET = "11111111-2222-3333-4444-555555555555"
PVE_VERSION = {"version": "8.3.0", "release": "8.3", "repoid": "abc123"}
PVE_NODES = [{"node": "pve2", "status": "online"}, {"node": "pve1", "status": "online"}]


def _stub_proxmox(monkeypatch: pytest.MonkeyPatch, handler: Any, seen: dict[str, Any]) -> None:
    def factory(insecure: bool) -> httpx.Client:
        seen["insecure"] = insecure
        return httpx.Client(transport=httpx.MockTransport(handler), headers={"Accept": "application/json"})

    monkeypatch.setattr(proxmox, "_client", factory)


def test_proxmox_api_token_verify_env_and_masking(platform: Platform, service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("Authorization") != f"PVEAPIToken=terraform@pve!hopshift={PVE_TOKEN_SECRET}":
            return httpx.Response(401, json={"data": None})
        if request.url.path == "/api2/json/version":
            return httpx.Response(200, json={"data": PVE_VERSION})
        if request.url.path == "/api2/json/nodes":
            return httpx.Response(200, json={"data": PVE_NODES})
        return httpx.Response(404, json={"data": None})

    seen: dict[str, Any] = {}
    _stub_proxmox(monkeypatch, handler, seen)
    connection = service.create(
        name="pve-lab", provider="proxmox", auth_method="api_token",
        config={"endpoint": "https://pve.example.internal:8006/api2/json/", "token_id": "terraform@pve!hopshift", "insecure": True},
        secret={"token_secret": PVE_TOKEN_SECRET}, actor="alice",
    )
    assert connection.config == {"endpoint": "https://pve.example.internal:8006/api2/json/", "token_id": "terraform@pve!hopshift", "insecure": True}

    result = service.test(connection.id, actor="bob")
    assert result["ok"] is True, result["message"]
    assert result["identity"] == {
        "endpoint": "https://pve.example.internal:8006", "principal": "terraform@pve!hopshift", "version": "8.3.0", "release": "8.3",
        "repoid": "abc123", "insecure": True, "nodes": 2, "node_names": ["pve1", "pve2"],
    }
    assert result["message"] == "authenticated to Proxmox VE 8.3.0 as terraform@pve!hopshift"
    assert seen["insecure"] is True
    assert [str(r.url) for r in requests] == ["https://pve.example.internal:8006/api2/json/version", "https://pve.example.internal:8006/api2/json/nodes"]
    assert service.get(connection.id).status == "ok"

    assert service.terraform_env(connection.id) == {
        "PROXMOX_VE_ENDPOINT": "https://pve.example.internal:8006/", "PROXMOX_VE_INSECURE": "true",
        "PROXMOX_VE_API_TOKEN": f"terraform@pve!hopshift={PVE_TOKEN_SECRET}",
    }
    assert service.secret_values(connection.id) == [f"terraform@pve!hopshift={PVE_TOKEN_SECRET}", PVE_TOKEN_SECRET]
    entries, _ = platform.audit.list(action="connection.tested")
    assert entries[0].outcome == "success" and PVE_TOKEN_SECRET not in json.dumps(entries[0].details)

    # a rejected token is a failed check with a short message, not an exception
    wrong = service.update(connection.id, secret={"token_secret": "00000000-0000-0000-0000-000000000000"}, actor="alice")
    assert wrong.status == "unverified"
    failed = service.test(connection.id, actor="bob")
    assert failed["ok"] is False and failed["message"] == "Proxmox VE rejected the credentials (401)"
    assert service.get(connection.id).status == "failed"


def test_proxmox_password_verify_env_and_failures(service: ConnectionService, monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.parse import parse_qs

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api2/json/access/ticket" and request.method == "POST":
            form = parse_qs(request.content.decode())
            if form == {"username": ["terraform@pve"], "password": ["pve-password-value"]}:
                return httpx.Response(200, json={"data": {"ticket": "PVE:terraform@pve:AAAA::BBBB", "CSRFPreventionToken": "csrf-token", "username": "terraform@pve"}})
            return httpx.Response(401, json={"data": None})
        if request.headers.get("Cookie") != "PVEAuthCookie=PVE:terraform@pve:AAAA::BBBB":
            return httpx.Response(401, json={"data": None})
        if request.url.path == "/api2/json/version":
            return httpx.Response(200, json={"data": PVE_VERSION})
        if request.url.path == "/api2/json/nodes":
            return httpx.Response(403, json={"data": None, "message": "permission check failed"})
        return httpx.Response(404, json={"data": None})

    seen: dict[str, Any] = {}
    _stub_proxmox(monkeypatch, handler, seen)
    connection = service.create(
        name="pve-pw", provider="proxmox", auth_method="password",
        config={"endpoint": "https://pve.example.internal:8006", "username": "terraform@pve"}, secret={"password": "pve-password-value"}, actor="alice",
    )
    assert connection.config["insecure"] is False  # catalog default

    result = service.test(connection.id)
    assert result["ok"] is True, result["message"]
    assert seen["insecure"] is False
    assert [r.url.path for r in requests] == ["/api2/json/access/ticket", "/api2/json/version", "/api2/json/nodes"]
    assert requests[1].headers["CSRFPreventionToken"] == "csrf-token"
    assert result["identity"]["principal"] == "terraform@pve" and result["identity"]["version"] == "8.3.0"
    assert "nodes" not in result["identity"]  # listing nodes needs Sys.Audit; the check still succeeds

    assert service.terraform_env(connection.id) == {
        "PROXMOX_VE_ENDPOINT": "https://pve.example.internal:8006/", "PROXMOX_VE_INSECURE": "false",
        "PROXMOX_VE_USERNAME": "terraform@pve", "PROXMOX_VE_PASSWORD": "pve-password-value",
    }
    assert service.secret_values(connection.id) == ["pve-password-value"]

    service.update(connection.id, secret={"password": "wrong-password"}, actor="alice")
    failed = service.test(connection.id)
    assert failed["ok"] is False and failed["message"] == "Proxmox VE rejected the username or password (401)"
    assert "wrong-password" not in json.dumps(failed)


def test_proxmox_endpoint_normalisation() -> None:
    assert proxmox.normalise_endpoint("https://pve:8006/") == "https://pve:8006"
    assert proxmox.normalise_endpoint(" https://pve:8006/api2/json ") == "https://pve:8006"
    assert proxmox.normalise_endpoint("https://pve:8006/API2/JSON/") == "https://pve:8006"
    assert proxmox.api_token(" user@pam!tok ", "secret") == "user@pam!tok=secret"


# ── rotation ──────────────────────────────────────────────────────────────────


def test_rotate_secrets_reencrypts_with_the_primary_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_key, new_key = SecretBox.generate_key(), SecretBox.generate_key()
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", old_key)
    platform = Platform.from_config({"runtime": {"platform_db": str(tmp_path / "rot.sqlite")}})
    service = platform.connections
    connection = service.create(name="lab", provider="aws", auth_method="access_keys", config=AWS_KEYS, secret=AWS_SECRET, actor="alice")
    service.create(name="env", provider="aws", auth_method="environment", config={"region": "us-east-1"}, secret={}, actor="alice")
    assert service.rotate_secrets() == 1  # same key: still re-encrypted, still readable

    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", f"{new_key},{old_key}")
    platform.secrets = SecretBox.from_env()
    assert service.rotate_secrets() == 1
    token = service.get(connection.id).secret_token or ""
    assert SecretBox([new_key]).decrypt_json(token) == AWS_SECRET
    assert service.terraform_env(connection.id)["AWS_SECRET_ACCESS_KEY"] == AWS_SECRET["secret_access_key"]

    platform.secrets = SecretBox([SecretBox.generate_key()])
    with pytest.raises(Unavailable, match="cannot be decrypted"):
        service.terraform_env(connection.id)
    assert service.test(connection.id)["ok"] is False and service.get(connection.id).status == "failed"
