from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient

from hopshift.api.app import create_app
from hopshift.pipeline.runtime import MigrationRuntime
from hopshift.services.secrets import SecretBox

PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "another long passphrase 42"


def _config(**auth: object) -> dict[str, object]:
    return {
        "generation": {"mode": "deterministic"},
        "mcp": {"enabled": False},
        "validation": {"run_terraform_validate": False, "run_tflint": False, "run_opa": False},
        "output": {"base_dir": "output"},
        "required_tags": {"MigratedFrom": "vmware-vcenter"},
        "runtime": {"default_pause_points": ["review_cim"]},
        "security": {
            "auth": {"mode": "required", "session_hours": 12, "idle_minutes": 60, "lockout_threshold": 3, "lockout_minutes": 15, **auth},
            "retention": {"runs_days": 0, "audit_days": 0},
        },
    }


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **auth: object) -> TestClient:
    monkeypatch.setenv("HOPSHIFT_SECRET_KEY", SecretBox.generate_key())
    runtime = MigrationRuntime(_config(**auth), runs_dir=tmp_path / "runs", checkpoint_db=tmp_path / "runs" / "cp.sqlite")
    app = create_app(runtime=runtime)  # in-memory platform database
    # Cookie-authenticated mutations must carry a same-origin Origin header (OriginCheckMiddleware).
    return TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    return _make_client(tmp_path, monkeypatch)


def _setup_admin(client: TestClient, username: str = "admin") -> dict[str, object]:
    response = client.post("/api/auth/setup", json={"username": username, "password": PASSWORD, "name": "Admin"})
    assert response.status_code == 201, response.text
    return response.json()


def _login(client: TestClient, username: str, password: str, totp_code: str | None = None):
    body: dict[str, object] = {"username": username, "password": password}
    if totp_code is not None:
        body["totp_code"] = totp_code
    return client.post("/api/auth/login", json=body)


# ── setup, login, logout ──────────────────────────────────────────────────────


def test_setup_login_logout_flow(client: TestClient) -> None:
    status = client.get("/api/auth/status").json()
    assert status == {"setup_required": True, "auth_mode": "required", "oidc_enabled": False, "mfa_policy": "optional", "user": None}
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    created = client.post("/api/auth/setup", json={"username": "  Admin ", "password": PASSWORD, "name": "Admin"})
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "admin" and created.json()["role"] == "admin"
    assert created.json()["mfa_enabled"] is False
    set_cookie = created.headers["set-cookie"]
    assert "hopshift_session=" in set_cookie and "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie and "Path=/" in set_cookie
    assert "Secure" not in set_cookie  # plain http in tests
    assert "password_hash" not in created.text and PASSWORD not in created.text

    response = client.post("/api/auth/setup", json={"username": "second", "password": PASSWORD, "name": "x"})
    assert response.status_code == 409

    status = client.get("/api/auth/status").json()
    assert status["setup_required"] is False and status["user"]["username"] == "admin"
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["auth_kind"] == "password" and me["principal"]["kind"] == "user"
    assert client.get("/api/runs").status_code == 200

    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set("hopshift_session", "stale-or-expired-value")
    stale = client.post("/api/auth/logout")  # logout never fails and always clears the cookie
    assert stale.status_code == 204 and 'hopshift_session=""' in stale.headers["set-cookie"]
    client.cookies.clear()

    wrong = _login(client, "admin", "definitely not the password")
    unknown = _login(client, "nobody", "definitely not the password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid username or password"}

    ok = _login(client, " ADMIN ", PASSWORD)  # case-insensitive, trimmed
    assert ok.status_code == 200 and ok.json()["username"] == "admin" and ok.json()["last_login_at"]
    assert client.get("/api/runs").status_code == 200

    entries = client.get("/api/audit?action=auth.login").json()
    assert entries["total"] >= 3
    failures = [entry for entry in entries["entries"] if entry["outcome"] == "failure"]
    assert {entry["actor"] for entry in failures} == {"admin", "nobody"}
    assert all("definitely not the password" not in str(entry["details"]) for entry in failures)  # never the secret itself
    assert all(set(entry["details"]) == {"reason"} for entry in failures)
    assert all(entry["ip"] and entry["user_agent"] for entry in entries["entries"])


def test_secure_cookie_behind_tls_proxy(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup", json={"username": "admin", "password": PASSWORD, "name": "Admin"}, headers={"X-Forwarded-Proto": "https"}
    )
    assert response.status_code == 201
    assert "Secure" in response.headers["set-cookie"]


def test_password_policy_and_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    short = client.post("/api/auth/setup", json={"username": "admin", "password": "short", "name": "A"})
    assert short.status_code == 400 and "12" in short.text
    contains = client.post("/api/auth/setup", json={"username": "administrator", "password": "my administrator pw", "name": "A"})
    assert contains.status_code == 400 and "username" in contains.text
    _setup_admin(client)

    other = TestClient(client.app, headers={"Origin": "http://testserver"})
    assert _login(other, "admin", PASSWORD).status_code == 200
    assert other.get("/api/auth/me").status_code == 200

    bad = client.post("/api/auth/password", json={"current_password": "nope nope nope", "new_password": OTHER_PASSWORD})
    assert bad.status_code == 403
    weak = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "tiny"})
    assert weak.status_code == 400
    changed = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD})
    assert changed.status_code == 204

    assert client.get("/api/auth/me").status_code == 200  # the current session survives
    assert other.get("/api/auth/me").status_code == 401  # other sessions are revoked
    assert _login(other, "admin", PASSWORD).status_code == 401
    assert _login(other, "admin", OTHER_PASSWORD).status_code == 200


# ── API tokens ────────────────────────────────────────────────────────────────


def test_api_tokens(client: TestClient) -> None:
    _setup_admin(client)
    created = client.post("/api/auth/tokens", json={"name": "ci", "role": "operator", "expires_days": 30})
    assert created.status_code == 201, created.text
    payload = created.json()
    token = payload["token"]
    assert token.startswith("hs_") and len(token) > 40 and payload["prefix"] == token[:12]
    assert payload["role"] == "operator" and payload["expires_at"]

    listed = client.get("/api/auth/tokens").json()
    assert [item["name"] for item in listed] == ["ci"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]

    bearer = TestClient(client.app, headers={"Authorization": f"Bearer {token}"})
    assert bearer.get("/api/runs").status_code == 200
    assert bearer.get("/api/users").status_code == 403  # operator token cannot use admin endpoints
    assert bearer.get("/api/auth/me").json()["principal"]["kind"] == "token"
    response = bearer.post("/api/auth/tokens", json={"name": "chain"})
    assert response.status_code == 403  # tokens cannot mint tokens
    response = bearer.post("/api/auth/mfa/enroll")
    assert response.status_code == 403

    assert TestClient(client.app).get("/api/runs", headers={"Authorization": "Bearer hs_not_a_real_token"}).status_code == 401
    assert TestClient(client.app).get("/api/runs", headers={"Authorization": "Basic abc"}).status_code == 401

    response = client.delete(f"/api/auth/tokens/{payload['id']}")
    assert response.status_code == 204
    assert bearer.get("/api/runs").status_code == 401
    assert client.get("/api/auth/tokens").json() == []
    response = client.delete(f"/api/auth/tokens/{payload['id']}")
    assert response.status_code == 404

    # A viewer cannot create a token above their role, and cannot list everyone's tokens.
    client.post("/api/users", json={"username": "viewer", "password": OTHER_PASSWORD, "name": "V", "role": "viewer"})
    viewer = TestClient(client.app, headers={"Origin": "http://testserver"})
    assert _login(viewer, "viewer", OTHER_PASSWORD).status_code == 200
    response = viewer.post("/api/auth/tokens", json={"name": "escalate", "role": "admin"})
    assert response.status_code == 403
    own = viewer.post("/api/auth/tokens", json={"name": "mine"})
    assert own.status_code == 201 and own.json()["role"] == "viewer"
    assert viewer.get("/api/auth/tokens?all=true").status_code == 403
    assert {item["username"] for item in client.get("/api/auth/tokens?all=true").json()} == {"viewer"}
    response = viewer.delete(f"/api/auth/tokens/{own.json()['id']}")
    assert response.status_code == 204

    actions = [entry["action"] for entry in client.get("/api/audit?limit=100").json()["entries"]]
    assert "auth.token_created" in actions and "auth.token_deleted" in actions


# ── users ─────────────────────────────────────────────────────────────────────


def test_user_administration(client: TestClient) -> None:
    admin = _setup_admin(client)
    created = client.post("/api/users", json={"username": "Bob", "password": OTHER_PASSWORD, "name": "Bob", "role": "viewer"})
    assert created.status_code == 201 and created.json()["username"] == "bob"
    bob_id = created.json()["id"]
    response = client.post("/api/users", json={"username": "bob", "password": OTHER_PASSWORD, "name": "Bob", "role": "viewer"})
    assert response.status_code == 409
    response = client.post("/api/users", json={"username": "eve", "password": OTHER_PASSWORD, "name": "Eve", "role": "root"})
    assert response.status_code == 400
    response = client.post("/api/users", json={"username": "bad name!", "password": OTHER_PASSWORD, "name": "x", "role": "viewer"})
    assert response.status_code == 400
    assert {user["username"] for user in client.get("/api/users").json()} == {"admin", "bob"}

    bob = TestClient(client.app, headers={"Origin": "http://testserver"})
    assert _login(bob, "bob", OTHER_PASSWORD).status_code == 200
    assert bob.get("/api/users").status_code == 403
    assert bob.get("/api/audit").status_code == 403
    response = bob.post("/api/runs", json={"discovery": {}, "options": {"cloud": "aws", "environment": "d", "owner": "o"}})
    assert response.status_code == 403

    promoted = client.patch(f"/api/users/{bob_id}", json={"role": "operator"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "operator"
    assert bob.get("/api/auth/me").json()["role"] == "operator"

    response = client.delete(f"/api/users/{admin['id']}")
    assert response.status_code == 409  # cannot delete yourself
    response = client.patch(f"/api/users/{admin['id']}", json={"role": "viewer"})
    assert response.status_code == 409  # last admin
    response = client.patch(f"/api/users/{admin['id']}", json={"disabled": True})
    assert response.status_code == 409

    disabled = client.patch(f"/api/users/{bob_id}", json={"disabled": True})
    assert disabled.status_code == 200 and disabled.json()["disabled"] is True
    assert bob.get("/api/auth/me").status_code == 401  # sessions revoked
    assert _login(bob, "bob", OTHER_PASSWORD).status_code == 401  # generic failure for disabled accounts

    response = client.patch(f"/api/users/{bob_id}", json={"disabled": False, "password": PASSWORD})
    assert response.status_code == 200
    assert _login(bob, "bob", PASSWORD).status_code == 200

    response = client.delete(f"/api/users/{bob_id}")
    assert response.status_code == 204
    assert client.get(f"/api/users/{bob_id}").status_code == 404
    assert bob.get("/api/auth/me").status_code == 401

    actions = [entry["action"] for entry in client.get("/api/audit?target_type=user").json()["entries"]]
    assert {"user.created", "user.updated", "user.deleted"} <= set(actions)


# ── MFA ───────────────────────────────────────────────────────────────────────


def test_mfa_enrolment_login_recovery_and_disable(client: TestClient) -> None:
    _setup_admin(client)
    enrolled = client.post("/api/auth/mfa/enroll")
    assert enrolled.status_code == 200
    secret = enrolled.json()["secret"]
    assert enrolled.json()["otpauth_uri"].startswith("otpauth://totp/hopshift:admin?")
    assert "issuer=hopshift" in enrolled.json()["otpauth_uri"]
    totp = pyotp.TOTP(secret)

    response = client.post("/api/auth/mfa/confirm", json={"code": "000000"})
    assert response.status_code == 403
    confirmed = client.post("/api/auth/mfa/confirm", json={"code": totp.at(datetime.now(timezone.utc), -1)})
    assert confirmed.status_code == 200, confirmed.text
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == 8 and all(len(code) == 11 and "-" in code for code in codes)
    assert client.get("/api/auth/me").json()["mfa_enabled"] is True
    response = client.post("/api/auth/mfa/enroll")
    assert response.status_code == 409

    client.post("/api/auth/logout")
    challenge = _login(client, "admin", PASSWORD)
    assert challenge.status_code == 401 and challenge.json() == {"detail": "mfa_required", "mfa_required": True}
    assert "set-cookie" not in challenge.headers
    bad_code = _login(client, "admin", PASSWORD, totp_code="123456")
    assert bad_code.status_code == 401 and bad_code.json()["mfa_required"] is True

    current = totp.now()
    assert _login(client, "admin", PASSWORD, totp_code=current).status_code == 200
    client.post("/api/auth/logout")
    replay = _login(client, "admin", PASSWORD, totp_code=current)
    assert replay.status_code == 401 and replay.json()["mfa_required"] is True  # a code is accepted once

    recovered = _login(client, "admin", PASSWORD, totp_code=codes[0].upper())
    assert recovered.status_code == 200
    client.post("/api/auth/logout")
    reused = _login(client, "admin", PASSWORD, totp_code=codes[0])
    assert reused.status_code == 401 and reused.json()["mfa_required"] is True  # single use
    assert _login(client, "admin", PASSWORD, totp_code=codes[1]).status_code == 200

    response = client.post("/api/auth/mfa/disable", json={"password": "wrong password here", "code": codes[2]})
    assert response.status_code == 403
    response = client.post("/api/auth/mfa/disable", json={"password": PASSWORD, "code": "000000"})
    assert response.status_code == 403
    response = client.post("/api/auth/mfa/disable", json={"password": PASSWORD, "code": codes[2]})
    assert response.status_code == 204
    assert client.get("/api/auth/me").json()["mfa_enabled"] is False
    client.post("/api/auth/logout")
    assert _login(client, "admin", PASSWORD).status_code == 200

    actions = {entry["action"] for entry in client.get("/api/audit?limit=200").json()["entries"]}
    assert {"auth.mfa_enrolled", "auth.mfa_confirmed", "auth.recovery_code_used", "auth.mfa_disabled"} <= actions
    export = client.get("/api/audit/export")
    assert export.status_code == 200 and export.headers["content-type"].startswith("application/x-ndjson")
    assert secret not in export.text and PASSWORD not in export.text


def test_mfa_required_policy_blocks_everything_but_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch, mfa="required")
    _setup_admin(client)
    assert client.get("/api/auth/status").json()["mfa_policy"] == "required"
    assert client.get("/api/auth/me").json()["mfa_enrollment_required"] is True
    blocked = client.get("/api/runs")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "mfa_enrollment_required"
    assert client.get("/api/users").status_code == 403
    response = client.post("/api/auth/tokens", json={"name": "ci"})
    assert response.status_code == 403

    secret = client.post("/api/auth/mfa/enroll").json()["secret"]
    response = client.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200
    assert client.get("/api/auth/me").json()["mfa_enrollment_required"] is False
    assert client.get("/api/runs").status_code == 200
    response = client.post("/api/auth/tokens", json={"name": "ci"})
    assert response.status_code == 201

    # An admin can reset a lost second factor; the user is then back in enrolment mode.
    user_id = client.get("/api/auth/me").json()["id"]
    client.post("/api/users", json={"username": "second", "password": OTHER_PASSWORD, "name": "S", "role": "admin"})
    second = TestClient(client.app, headers={"Origin": "http://testserver"})
    assert _login(second, "second", OTHER_PASSWORD).status_code == 200
    response = second.post(f"/api/users/{user_id}/mfa/reset")
    assert response.status_code == 403  # the policy applies to admins too
    second_secret = second.post("/api/auth/mfa/enroll").json()["secret"]
    response = second.post("/api/auth/mfa/confirm", json={"code": pyotp.TOTP(second_secret).now()})
    assert response.status_code == 200
    reset = second.post(f"/api/users/{user_id}/mfa/reset")
    assert reset.status_code == 200 and reset.json()["mfa_enabled"] is False
    assert client.get("/api/auth/me").status_code == 401  # sessions of the reset user are revoked


# ── lockout and throttling ────────────────────────────────────────────────────


def test_lockout_after_repeated_failures(client: TestClient) -> None:
    _setup_admin(client)
    client.post("/api/auth/logout")
    for _ in range(3):
        assert _login(client, "admin", "wrong password here").status_code == 401
    locked = _login(client, "admin", PASSWORD)
    assert locked.status_code == 423 and int(locked.headers["retry-after"]) > 0
    assert "password" not in locked.json()["detail"]
    # an unknown username is throttled the same way, so lockout does not reveal which accounts exist
    for _ in range(3):
        _login(client, "ghost", "wrong password here")
    assert _login(client, "ghost", "wrong password here").status_code == 423

    assert _login(client, "admin", PASSWORD).status_code == 423
    other = TestClient(client.app, headers={"Origin": "http://testserver"})
    client.app.state.platform.auth.store.clear_attempts("admin")  # the lock window elapsed
    assert _login(other, "admin", PASSWORD).status_code == 200
    audit = other.get("/api/audit?action=auth.locked").json()
    assert audit["total"] == 2 and {entry["actor"] for entry in audit["entries"]} == {"admin", "ghost"}


def test_login_rate_limit_per_ip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch, login_rate_per_minute=5)
    _setup_admin(client)  # /auth/setup shares the per-IP bucket: one token spent
    client.post("/api/auth/logout")
    statuses = [_login(client, "admin", "wrong password here").status_code for _ in range(5)]
    assert statuses == [401, 401, 401, 423, 429]
    limited = _login(client, "admin", PASSWORD)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert limited.json()["detail"].startswith("too many requests")
    assert client.get("/api/auth/status").status_code == 200  # other endpoints are not throttled


# ── disabled mode, audit, posture ─────────────────────────────────────────────


def test_auth_disabled_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch, mode="disabled")
    status = client.get("/api/auth/status").json()
    assert status["auth_mode"] == "disabled" and status["setup_required"] is False
    assert status["user"]["role"] == "admin" and status["user"]["auth_kind"] == "anonymous"
    assert client.get("/api/auth/me").json()["username"] == "anonymous"
    assert client.get("/api/runs").status_code == 200
    response = client.post("/api/auth/setup", json={"username": "admin", "password": PASSWORD, "name": "A"})
    assert response.status_code == 400
    response = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 400
    assert client.get("/api/users").status_code == 400
    assert client.get("/api/audit").status_code == 200  # the audit log works without accounts
    checks = {check["id"]: check for check in client.get("/api/settings/posture").json()["checks"]}
    assert checks["auth.enforced"]["status"] == "fail"
    assert client.get("/api/meta").json()["auth_mode"] == "disabled"


def test_audit_endpoints_and_posture(client: TestClient) -> None:
    _setup_admin(client)
    listed = client.get("/api/audit?limit=2&offset=0")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 1 and len(body["entries"]) <= 2 and body["entries"][0]["action"] in {"auth.setup", "auth.login"}
    filtered = client.get("/api/audit?actor=admin&outcome=success&target_type=user").json()
    assert filtered["total"] >= 1 and all(entry["actor"] == "admin" for entry in filtered["entries"])
    assert client.get("/api/audit?since=2999-01-01T00:00:00").json()["total"] == 0
    verify = client.get("/api/audit/verify").json()
    assert verify["ok"] is True and verify["entries"] >= 1 and verify["message"] == "chain intact"
    export = client.get("/api/audit/export")
    lines = [line for line in export.text.splitlines() if line]
    assert len(lines) == verify["entries"] and '"action":"auth.setup"' in lines[0]

    posture = client.get("/api/settings/posture").json()["checks"]
    ids = [check["id"] for check in posture]
    for expected in (
        "auth.enforced", "secrets.key", "audit.chain", "transport.tls", "retention.runs", "mfa.policy", "mfa.coverage",
        "mfa.secrets_encrypted", "oidc.configured", "api.docs", "session.lifetime", "auth.lockout", "runs.encrypt_inputs",
        "deploy.allow_destroy", "retention.audit",
    ):
        assert expected in ids, expected
    by_id = {check["id"]: check for check in posture}
    assert by_id["auth.enforced"]["status"] == "pass" and by_id["secrets.key"]["status"] == "pass"
    assert by_id["mfa.coverage"]["status"] == "warn" and "1 active" in by_id["mfa.coverage"]["detail"]
    assert all({"id", "title", "status", "detail", "frameworks"} <= set(check) for check in posture)
    assert all(check["status"] in {"pass", "warn", "fail"} for check in posture)
    assert client.get("/api/auth/oidc/login").status_code == 400  # not configured
