from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import vma.connections.aws as aws
from agent.runtime import MigrationRuntime
from api.app import create_app
from api.deps import Principal
from vma.secrets import SecretBox

AWS_BODY = {
    "name": "lab", "provider": "aws", "auth_method": "access_keys",
    "config": {"access_key_id": "AKIAEXAMPLEKEY", "region": "eu-west-1"}, "secret": {"secret_access_key": "wJalrXUtnFEMI/K7MDENG"},
}


def _config() -> dict[str, object]:
    return {
        "generation": {"mode": "deterministic"}, "mcp": {"enabled": False},
        "validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": False},
        "output": {"base_dir": "output"}, "runtime": {"default_pause_points": []},
        "security": {"auth": {"mode": "disabled"}},  # the HTTP tests exercise the service, not sign-in
    }


def _client(tmp_path: Path) -> TestClient:
    runtime = MigrationRuntime(_config(), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "runs" / "cp.sqlite")
    return TestClient(create_app(runtime=runtime))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VMA_SECRET_KEY", SecretBox.generate_key())
    return _client(tmp_path)


class _FakeAuth:
    """Minimal stand-in for the security workstream: every request is the configured principal."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    def authenticate(self, request: Request) -> Principal:
        return self.principal


def _as_role(client: TestClient, role: str) -> None:
    # the fixture runs with auth disabled; role checks need the required mode plus a fake principal
    client.app.state.platform.config.setdefault("security", {}).setdefault("auth", {})["mode"] = "required"
    client.app.state.platform.auth = _FakeAuth(Principal(subject=f"{role}-user", kind="user", role=role))


def _stub_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aws, "get_caller_identity", lambda session, *, region, endpoint_url: {"account": "123456789012", "arn": "arn:aws:iam::123456789012:user/m", "user_id": "AID"})


def test_methods_catalog(client: TestClient) -> None:
    response = client.get("/api/connections/methods")
    assert response.status_code == 200
    catalog = response.json()
    assert set(catalog) == {"aws", "azure", "gcp", "openstack"}
    method = next(m for m in catalog["aws"]["methods"] if m["key"] == "access_keys")
    assert any(f["key"] == "secret_access_key" and f["secret"] and f["type"] == "password" for f in method["fields"])
    assert client.get("/api/meta").json()["features"]["connections"] is True


def test_connection_crud_and_test_over_http(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_identity(monkeypatch)
    created = client.post("/api/connections", json=AWS_BODY)
    assert created.status_code == 201, created.text
    payload = created.json()
    connection_id = payload["id"]
    assert payload["status"] == "unverified" and payload["has_secret"] is True and payload["secret_fields"] == ["secret_access_key"]
    assert payload["terraform_ready"] is True and payload["config"] == AWS_BODY["config"] and payload["created_by"] == "anonymous"
    assert "wJalrXUtnFEMI" not in created.text

    listed = client.get("/api/connections").json()
    assert [item["id"] for item in listed] == [connection_id]
    assert client.get("/api/connections?provider=azure").json() == []
    assert client.get(f"/api/connections/{connection_id}").json()["name"] == "lab"

    tested = client.post(f"/api/connections/{connection_id}/test")
    assert tested.status_code == 200
    assert tested.json()["ok"] is True and tested.json()["identity"]["account"] == "123456789012"
    assert client.get(f"/api/connections/{connection_id}").json()["status"] == "ok"

    patched = client.patch(f"/api/connections/{connection_id}", json={"name": "lab-2", "secret": {"session_token": "FwoGZXIvYXdzE"}})
    assert patched.status_code == 200
    assert patched.json()["name"] == "lab-2" and patched.json()["secret_fields"] == ["secret_access_key", "session_token"] and patched.json()["status"] == "unverified"
    assert "FwoGZXIvYXdzE" not in patched.text

    deleted = client.delete(f"/api/connections/{connection_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/connections/{connection_id}").status_code == 404

    entries, total = client.app.state.platform.audit.list()
    actions = [entry.action for entry in entries]
    assert actions == ["connection.deleted", "connection.updated", "connection.tested", "connection.created"]
    assert all(entry.actor == "anonymous" and entry.target_id == connection_id for entry in entries)
    assert "wJalrXUtnFEMI" not in json.dumps([entry.details for entry in entries])


def test_http_error_mapping(client: TestClient) -> None:
    assert client.post("/api/connections", json=AWS_BODY).status_code == 201
    duplicate = client.post("/api/connections", json=AWS_BODY)
    assert duplicate.status_code == 409 and "already exists" in duplicate.text

    invalid = client.post("/api/connections", json={**AWS_BODY, "name": "x", "config": {"bogus": "1"}})
    assert invalid.status_code == 400 and "unknown field 'bogus'" in invalid.text
    assert client.post("/api/connections", json={**AWS_BODY, "name": "y", "provider": "nope"}).status_code == 400

    assert client.get("/api/connections/missing").status_code == 404
    assert client.post("/api/connections/missing/test").status_code == 404
    assert client.patch("/api/connections/missing", json={"name": "z"}).status_code == 404
    assert client.delete("/api/connections/missing").status_code == 404
    assert client.post("/api/connections/missing/device/start").status_code == 404

    environment = client.post("/api/connections", json={"name": "env", "provider": "aws", "auth_method": "environment", "config": {"region": "us-east-1"}}).json()
    assert client.post(f"/api/connections/{environment['id']}/device/start").status_code == 400
    assert client.post(f"/api/connections/{environment['id']}/device/poll", json={"flow_id": "nope"}).status_code == 404


def test_secrets_unavailable_maps_to_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VMA_SECRET_KEY", raising=False)
    client = _client(tmp_path)
    assert client.get("/api/meta").json()["features"]["secrets"] is False
    response = client.post("/api/connections", json=AWS_BODY)
    assert response.status_code == 503 and "VMA_SECRET_KEY" in response.text
    without_secret = client.post("/api/connections", json={"name": "env", "provider": "aws", "auth_method": "environment", "config": {"region": "us-east-1"}})
    assert without_secret.status_code == 201


def test_roles_are_enforced(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_identity(monkeypatch)
    connection_id = client.post("/api/connections", json=AWS_BODY).json()["id"]

    _as_role(client, "viewer")
    assert client.get("/api/connections").status_code == 200
    assert client.get("/api/connections/methods").status_code == 200
    assert client.get(f"/api/connections/{connection_id}").status_code == 200
    assert client.post(f"/api/connections/{connection_id}/test").status_code == 403
    assert client.post("/api/connections", json={**AWS_BODY, "name": "other"}).status_code == 403
    assert client.patch(f"/api/connections/{connection_id}", json={"name": "x"}).status_code == 403
    assert client.delete(f"/api/connections/{connection_id}").status_code == 403

    _as_role(client, "operator")
    assert client.post(f"/api/connections/{connection_id}/test").status_code == 200
    assert client.post("/api/connections", json={**AWS_BODY, "name": "other"}).status_code == 403
    assert client.delete(f"/api/connections/{connection_id}").status_code == 403

    _as_role(client, "admin")
    assert client.patch(f"/api/connections/{connection_id}", json={"name": "renamed"}).status_code == 200
    assert client.delete(f"/api/connections/{connection_id}").status_code == 204
    entries, _ = client.app.state.platform.audit.list(action="connection.tested")
    assert entries[0].actor == "operator-user" and entries[0].user_agent == "testclient"


def test_sso_device_flow_over_http(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([{"status": "pending"}, {"status": "complete", "access_token": "SSOTOKEN", "expires_in": 3600}])
    monkeypatch.setattr(aws, "sso_register_client", lambda *, sso_region: {"client_id": "cid", "client_secret": "csecret", "client_secret_expires_at": 0})
    monkeypatch.setattr(aws, "sso_start_device_authorization", lambda **kw: {
        "device_code": "DEVCODE", "user_code": "ABCD-EFGH", "verification_uri": "https://device.sso.eu-west-1.amazonaws.com/",
        "verification_uri_complete": "https://device.sso.eu-west-1.amazonaws.com/?user_code=ABCD-EFGH", "expires_in": 600, "interval": 1,
    })
    monkeypatch.setattr(aws, "sso_create_token", lambda **kw: next(results))
    monkeypatch.setattr(aws, "sso_role_credentials", lambda **kw: {"access_key_id": "ASIASSO", "secret_access_key": "s", "session_token": "t", "expiration": None})
    _stub_identity(monkeypatch)

    created = client.post("/api/connections", json={
        "name": "sso", "provider": "aws", "auth_method": "sso",
        "config": {"start_url": "https://acme.awsapps.com/start", "sso_region": "eu-west-1", "account_id": "123456789012", "role_name": "Migrator", "region": "eu-west-1"},
    })
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]

    started = client.post(f"/api/connections/{connection_id}/device/start")
    assert started.status_code == 200, started.text
    body = started.json()
    assert set(body) == {"flow_id", "user_code", "verification_uri", "verification_uri_complete", "expires_in", "interval"}
    assert "csecret" not in started.text and "DEVCODE" not in started.text

    pending = client.post(f"/api/connections/{connection_id}/device/poll", json={"flow_id": body["flow_id"]})
    assert pending.status_code == 200 and pending.json()["status"] == "pending"
    done = client.post(f"/api/connections/{connection_id}/device/poll", json={"flow_id": body["flow_id"]})
    assert done.status_code == 200 and done.json()["status"] == "complete"
    assert "SSOTOKEN" not in done.text

    connection = client.get(f"/api/connections/{connection_id}").json()
    assert connection["status"] == "ok" and connection["secret_fields"] == ["sso_access_token", "sso_token_expires_at"]
    assert "SSOTOKEN" not in json.dumps(connection)


def test_runs_can_reference_a_connection(client: TestClient) -> None:
    connection_id = client.post("/api/connections", json=AWS_BODY).json()["id"]
    discovery: dict[str, Any] = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "discovery_multi_vm.json").read_text(encoding="utf-8"))
    options = {"cloud": "aws", "environment": "dev", "owner": "platform"}
    assert client.post("/api/runs", json={"discovery": discovery, "options": options, "connection_id": "missing"}).status_code == 404
    created = client.post("/api/runs", json={"discovery": discovery, "options": options, "connection_id": connection_id})
    assert created.status_code == 201 and created.json()["connection_id"] == connection_id
