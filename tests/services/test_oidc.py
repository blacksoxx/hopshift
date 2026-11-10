from __future__ import annotations

import base64
import hashlib
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from hopshift.api.app import create_app
from hopshift.pipeline.runtime import MigrationRuntime
from hopshift.services.errors import Forbidden, Invalid
from hopshift.services.secrets import SecretBox
from hopshift.services.security import oidc as oidc_module
from hopshift.services.security.oidc import OIDCClient, OIDCConfig, pkce_pair

jwt = oidc_module.jwt
JsonWebKey = oidc_module.JsonWebKey

ISSUER = "https://idp.example.test"
CLIENT_ID = "vma-client"
CLIENT_SECRET = "very-secret-client-secret"
SECRET_ENV = "TEST_OIDC_CLIENT_SECRET"


class FakeIdP:
    """An OpenID provider served through httpx.MockTransport: discovery, JWKS, token endpoint."""

    def __init__(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.private_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.jwk = JsonWebKey.import_key(public_pem, {"kty": "RSA", "kid": "test-key", "use": "sig", "alg": "RS256"}).as_dict()
        self.expected_challenge: str | None = None
        self.current_nonce: str | None = None  # the nonce from the last authorization request
        self.nonce_override: str | None = None
        self.claims_override: dict[str, Any] = {}
        self.token_requests: list[dict[str, str]] = []
        self.requests: list[str] = []

    def claims(self, nonce: str) -> dict[str, Any]:
        now = int(time.time())
        base = {
            "iss": ISSUER, "sub": "subject-123", "aud": CLIENT_ID, "exp": now + 300, "iat": now, "nonce": nonce,
            "email": "Alice@Corp.Example", "email_verified": True, "name": "Alice Example", "groups": ["platform-admins", "everyone"],
        }
        base.update(self.claims_override)
        return base

    def id_token(self, nonce: str) -> str:
        return jwt.encode({"alg": "RS256", "kid": "test-key"}, self.claims(nonce), self.private_pem).decode("ascii")

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize", "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks", "userinfo_endpoint": f"{ISSUER}/userinfo",
            })
        if path == "/jwks":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path == "/token":
            form = dict(parse_qsl(request.content.decode("utf-8")))
            self.token_requests.append(form)
            if form.get("client_secret") != CLIENT_SECRET or form.get("grant_type") != "authorization_code":
                return httpx.Response(401, json={"error": "invalid_client"})
            if form.get("code") != "the-authorization-code":
                return httpx.Response(400, json={"error": "invalid_grant"})
            digest = hashlib.sha256(form["code_verifier"].encode("ascii")).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii") != self.expected_challenge:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "pkce"})
            nonce = self.nonce_override or self.current_nonce or ""
            return httpx.Response(200, json={"access_token": "access-token", "token_type": "Bearer", "id_token": self.id_token(nonce)})
        return httpx.Response(404, json={"error": "not_found"})


def _config(**oidc: Any) -> dict[str, Any]:
    return {
        "generation": {"mode": "deterministic"},
        "mcp": {"enabled": False},
        "validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": False},
        "output": {"base_dir": "output"},
        "required_tags": {"MigratedFrom": "vmware-vcenter"},
        "runtime": {"default_pause_points": []},
        "security": {
            "auth": {
                "mode": "required",
                "oidc": {
                    "enabled": True, "issuer": ISSUER, "client_id": CLIENT_ID, "client_secret_env": SECRET_ENV,
                    "scopes": ["openid", "profile", "email", "groups"], "allowed_domains": ["corp.example"],
                    "default_role": "viewer", "admin_groups": ["platform-admins"], "groups_claim": "groups", **oidc,
                },
            }
        },
    }


@pytest.fixture
def idp() -> FakeIdP:
    return FakeIdP()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, idp: FakeIdP) -> TestClient:
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", SecretBox.generate_key())
    monkeypatch.setenv(SECRET_ENV, CLIENT_SECRET)
    runtime = MigrationRuntime(_config(), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "runs" / "cp.sqlite")
    app = create_app(runtime=runtime)
    service = app.state.platform.auth
    assert service is not None and service.oidc is not None
    service.oidc.transport = httpx.MockTransport(idp.handler)
    return TestClient(app, headers={"Origin": "http://testserver"}, follow_redirects=False)


def _start_login(client: TestClient, idp: FakeIdP) -> dict[str, str]:
    response = client.get("/api/auth/oidc/login")
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
    query = dict(parse_qsl(location.query))
    assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["redirect_uri"] == "http://testserver/api/auth/oidc/callback"
    assert "openid" in query["scope"].split() and query["state"] and query["nonce"]
    idp.expected_challenge = query["code_challenge"]
    idp.current_nonce = query["nonce"]  # a real IdP learns it from the browser's authorization request
    return query


def _callback(client: TestClient, idp: FakeIdP, query: dict[str, str], code: str = "the-authorization-code", state: str | None = None):
    try:
        return client.get("/api/auth/oidc/callback", params={"code": code, "state": state if state is not None else query["state"]})
    finally:
        idp.nonce_override = None


def test_full_oidc_login_creates_admin_from_groups(client: TestClient, idp: FakeIdP) -> None:
    assert client.get("/api/auth/status").json()["oidc_enabled"] is True
    query = _start_login(client, idp)

    response = _callback(client, idp, query)
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/#/"
    assert "hopshift_session=" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    assert idp.requests.count("/.well-known/openid-configuration") == 1  # discovery is cached
    form = idp.token_requests[-1]
    assert form["redirect_uri"] == "http://testserver/api/auth/oidc/callback" and len(form["code_verifier"]) >= 43

    me = client.get("/api/auth/me").json()
    assert me["username"] == "alice@corp.example" and me["auth_kind"] == "oidc" and me["role"] == "admin"
    assert me["email"] == "alice@corp.example" and me["name"] == "Alice Example"
    assert me["mfa_enabled"] is False and me["mfa_enrollment_required"] is False and me["principal"]["mfa"] is True
    assert client.get("/api/runs").status_code == 200  # admin via group mapping

    users = client.get("/api/users").json()
    assert len(users) == 1 and users[0]["auth_kind"] == "oidc"
    audit = client.get("/api/audit?action=auth.oidc_login").json()
    assert audit["total"] == 1 and audit["entries"][0]["actor"] == "alice@corp.example" and audit["entries"][0]["outcome"] == "success"

    # the state is single use
    replay = _callback(client, idp, query)
    assert replay.status_code == 400 and "expired or is invalid" in replay.text

    # second login for the same subject reuses the account and syncs name and role from the claims;
    # the only remaining admin is never demoted by a group change
    idp.claims_override = {"groups": ["everyone"], "name": "Alice E."}
    client.cookies.clear()
    query = _start_login(client, idp)
    assert _callback(client, idp, query).status_code == 302
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["name"] == "Alice E."
    assert client.get("/api/auth/status").json()["user"]["username"] == "alice@corp.example"
    assert len(client.get("/api/users").json()) == 1  # no duplicate account

    service = client.app.state.platform.auth
    service.store.create_user(username="root", name="Root", role="admin", password_hash="x", auth_kind="password")
    client.cookies.clear()
    query = _start_login(client, idp)
    assert _callback(client, idp, query).status_code == 302
    me = client.get("/api/auth/me").json()
    assert me["role"] == "viewer"  # demotion applies once another admin exists
    assert client.get("/api/users").status_code == 403


def test_oidc_rejects_bad_nonce_domain_and_token_errors(client: TestClient, idp: FakeIdP) -> None:
    query = _start_login(client, idp)
    idp.nonce_override = "some-other-nonce"
    bad_nonce = _callback(client, idp, query)
    assert bad_nonce.status_code == 400 and "verification" in bad_nonce.text

    query = _start_login(client, idp)
    idp.claims_override = {"email": "mallory@evil.example"}
    wrong_domain = _callback(client, idp, query)
    assert wrong_domain.status_code == 403 and "domain" in wrong_domain.text
    idp.claims_override = {}

    query = _start_login(client, idp)
    rejected = _callback(client, idp, query, code="not-the-code")
    assert rejected.status_code == 400 and "rejected" in rejected.text

    assert client.get("/api/auth/oidc/callback", params={"code": "x", "state": "unknown"}).status_code == 400
    assert client.get("/api/auth/oidc/callback", params={"error": "access_denied", "state": query["state"]}).status_code == 400
    failures = client.app.state.platform.audit.list(action="auth.oidc_login", outcome="failure")[1]
    assert failures >= 4
    assert client.get("/api/auth/me").status_code == 401


def test_oidc_links_verified_email_to_existing_local_account(client: TestClient, idp: FakeIdP) -> None:
    service = client.app.state.platform.auth
    local = service.store.create_user(username="alice@corp.example", name="Local Alice", role="operator", password_hash="x", auth_kind="password")
    query = _start_login(client, idp)
    assert _callback(client, idp, query).status_code == 302
    me = client.get("/api/auth/me").json()
    assert me["id"] == local["id"] and me["auth_kind"] == "password" and me["role"] == "operator"  # local role kept

    # without a verified email the link is refused
    other = service.store.create_user(username="bob@corp.example", name="Bob", role="viewer", password_hash="x", auth_kind="password")
    idp.claims_override = {"sub": "subject-bob", "email": "bob@corp.example", "email_verified": False}
    client.cookies.clear()
    query = _start_login(client, idp)
    refused = _callback(client, idp, query)
    assert refused.status_code == 409 and service.store.get_user(other["id"])["oidc_subject"] is None


def test_oidc_client_helpers_and_pkce() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128 and len(challenge) == 43 and "=" not in challenge
    assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() == challenge

    config = OIDCConfig({"enabled": True, "issuer": ISSUER + "/", "client_id": CLIENT_ID, "allowed_domains": ["@Corp.Example"], "admin_groups": ["admins"], "default_role": "bogus"})
    assert config.configured and config.issuer == ISSUER and config.allowed_domains == ["corp.example"] and config.default_role == "viewer"
    assert "openid" in config.scopes
    assert not OIDCConfig({"enabled": True}).configured and not OIDCConfig(None).configured

    oidc = OIDCClient(config, client_secret=lambda: None)
    identity = oidc.identity_from_claims({"sub": "s", "email": "A@corp.example", "groups": ["admins"], "name": "A", "email_verified": True})
    assert identity["username"] == "a@corp.example" and identity["role"] == "admin" and identity["email_verified"] is True
    assert oidc.identity_from_claims({"sub": "s", "email": "b@corp.example", "groups": "other"})["role"] == "viewer"
    with pytest.raises(Forbidden):
        oidc.identity_from_claims({"sub": "s", "email": "x@other.example"})
    with pytest.raises(Invalid):
        oidc.identity_from_claims({"sub": "s"})
    with pytest.raises(Invalid):
        oidc.identity_from_claims({"email": "x@corp.example"})


def test_oidc_discovery_failures_are_unavailable(idp: FakeIdP) -> None:
    config = OIDCConfig({"enabled": True, "issuer": ISSUER, "client_id": CLIENT_ID})

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    oidc = OIDCClient(config, client_secret=lambda: CLIENT_SECRET, transport=httpx.MockTransport(broken))
    from hopshift.services.errors import Unavailable

    with pytest.raises(Unavailable):
        oidc.discover()
    good = OIDCClient(config, client_secret=lambda: None, transport=httpx.MockTransport(idp.handler))
    assert good.discover()["token_endpoint"] == f"{ISSUER}/token"
    with pytest.raises(Unavailable, match="client secret"):
        good.exchange_code(code="c", code_verifier="v", redirect_uri="https://app/cb")
