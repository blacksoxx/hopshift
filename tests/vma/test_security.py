from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyotp
import pytest
import yaml
from click.testing import CliRunner
from fastapi import HTTPException
from starlette.requests import Request

from cli.main import cli
from vma.errors import Conflict, Forbidden, Invalid
from vma.platform import Platform
from vma.secrets import SecretBox
from vma.security import auth_mode_of, build_auth_service, passwords
from vma.security.posture import posture_checks
from vma.security.ratelimit import TokenBucketLimiter
from vma.security.retention import sweep
from vma.security.service import AccountLocked, AuthService, LoginFailed, MfaRequired
from vma.security.store import SecurityStore, iso

PASSWORD = "correct horse battery staple"
CTX = {"ip": "203.0.113.7", "user_agent": "pytest"}


def _config(**auth: Any) -> dict[str, Any]:
    return {
        "security": {
            "auth": {"mode": "required", "session_hours": 2, "idle_minutes": 30, "lockout_threshold": 3, "lockout_minutes": 15, **auth},
            "retention": {"runs_days": 30, "audit_days": 90},
        }
    }


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Platform:
    monkeypatch.setenv("VMA_SECRET_KEY", SecretBox.generate_key())
    return Platform.from_config(_config(), db_path=tmp_path / "platform.sqlite")


@pytest.fixture
def service(platform: Platform) -> AuthService:
    assert isinstance(platform.auth, AuthService)
    return platform.auth


def _request(path: str = "/api/runs", *, bearer: str | None = None, cookie: str | None = None, https: bool = False) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"host", b"testserver"), (b"user-agent", b"pytest")]
    if bearer is not None:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    if cookie is not None:
        headers.append((b"cookie", f"vma_session={cookie}".encode()))
    scope = {
        "type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
        "scheme": "https" if https else "http", "server": ("testserver", 80), "client": ("127.0.0.1", 4242), "root_path": "",
    }
    return Request(scope)


def _setup(service: AuthService, username: str = "admin") -> tuple[dict[str, Any], str]:
    return service.setup(username, PASSWORD, "Admin", CTX)


def _sql(platform: Platform, statement: str, params: tuple[Any, ...] = ()) -> None:
    with platform.db.connect() as conn:
        conn.execute(statement, params)


# ── passwords ─────────────────────────────────────────────────────────────────


def test_password_policy_and_argon2id() -> None:
    with pytest.raises(Invalid, match="12"):
        passwords.validate_password("short", "alice")
    with pytest.raises(Invalid, match="username"):
        passwords.validate_password("alice-is-the-best-1", "alice")
    with pytest.raises(Invalid, match="username"):
        passwords.validate_password("Alice.Smith rocks 2024", "alice.smith@corp.example")
    passwords.validate_password(PASSWORD, "alice")

    digest = passwords.hash_password(PASSWORD)
    assert digest.startswith("$argon2id$") and PASSWORD not in digest
    assert passwords.verify_password(digest, PASSWORD)
    assert not passwords.verify_password(digest, PASSWORD + "x")
    assert not passwords.verify_password(None, PASSWORD)  # unknown user path still runs argon2 and fails
    assert not passwords.verify_password("garbage", PASSWORD)
    assert not passwords.needs_rehash(digest)


# ── modes and wiring ──────────────────────────────────────────────────────────


def test_build_auth_service_modes(tmp_path: Path) -> None:
    assert auth_mode_of({}) == "required"  # missing section: secure default
    assert auth_mode_of({"security": {"auth": {"mode": "DISABLED"}}}) == "disabled"
    assert auth_mode_of({"security": {"auth": {"mode": "whatever"}}}) == "required"

    enabled = Platform.from_config({}, db_path=tmp_path / "a.sqlite")
    assert isinstance(enabled.auth, AuthService) and enabled.auth_mode == "required"
    assert callable(enabled.extras.get("posture_checks"))
    for table in ("users", "sessions", "api_tokens", "mfa_recovery_codes", "oidc_states", "login_attempts"):
        assert table in enabled.db.table_names()

    disabled = Platform.from_config({"security": {"auth": {"mode": "disabled"}}}, db_path=tmp_path / "b.sqlite")
    assert disabled.auth is None and disabled.auth_mode == "disabled"
    assert build_auth_service(disabled) is None and callable(disabled.extras["posture_checks"])


# ── sessions ──────────────────────────────────────────────────────────────────


def test_setup_login_and_session_expiry(platform: Platform, service: AuthService) -> None:
    assert service.setup_required()
    user, token = _setup(service, "  Admin ")
    assert user["username"] == "admin" and user["role"] == "admin" and not service.setup_required()
    with pytest.raises(Conflict):
        _setup(service, "other")

    assert service.authenticate(_request()) is None  # no credential at all
    principal = service.authenticate(_request(cookie=token))
    assert principal is not None and principal.kind == "user" and principal.role == "admin" and principal.subject == "admin"
    assert principal.allows("operator") and not principal.mfa

    with pytest.raises(HTTPException) as denied:
        service.authenticate(_request(cookie="not-a-session"))
    assert denied.value.status_code == 401

    with pytest.raises(LoginFailed):
        service.login("admin", "wrong wrong wrong", None, CTX)
    with pytest.raises(LoginFailed):
        service.login("missing", PASSWORD, None, CTX)
    _user, token2 = service.login("ADMIN", PASSWORD, None, CTX)
    assert service.authenticate(_request(cookie=token2)) is not None

    session_hash = service.store.get_session_by_hash(hashlib.sha256(token2.encode()).hexdigest())
    assert session_hash is not None and token2 not in str(session_hash)  # only the hash is stored
    expires = datetime.fromisoformat(session_hash["expires_at"]) - datetime.fromisoformat(session_hash["created_at"])
    assert expires == timedelta(hours=2)

    # idle expiry: pretend the last activity was 31 minutes ago
    _sql(platform, "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (iso(datetime.now(timezone.utc) - timedelta(minutes=31)), session_hash["id"]))
    with pytest.raises(HTTPException) as idle:
        service.authenticate(_request(cookie=token2))
    assert idle.value.status_code == 401 and "inactivity" in idle.value.detail

    # absolute expiry
    _sql(platform, "UPDATE sessions SET expires_at = ? WHERE token_hash = ?", (iso(datetime.now(timezone.utc) - timedelta(seconds=1)), hashlib.sha256(token.encode()).hexdigest()))
    with pytest.raises(HTTPException) as expired:
        service.authenticate(_request(cookie=token))
    assert expired.value.status_code == 401

    # logout revokes
    _user, token3 = service.login("admin", PASSWORD, None, CTX)
    principal3 = service.authenticate(_request(cookie=token3))
    assert principal3 is not None
    service.logout(_request(cookie=token3), principal3, CTX)
    with pytest.raises(HTTPException):
        service.authenticate(_request(cookie=token3))

    actions = [entry.action for entry in platform.audit.iter_all()]
    assert actions.count("auth.login") >= 4 and "auth.logout" in actions and "auth.setup" in actions
    assert platform.audit.verify().ok


def test_api_tokens_roles_and_expiry(platform: Platform, service: AuthService) -> None:
    _user, cookie = _setup(service)
    admin = service.authenticate(_request(cookie=cookie))
    assert admin is not None
    created = service.create_token(admin, "ci", "operator", 30, CTX)
    token = created["token"]
    assert token.startswith("vma_") and created["prefix"] == token[:12]
    stored = service.store.get_token(created["id"])
    assert stored is not None and token not in str(stored)

    principal = service.authenticate(_request(bearer=token))
    assert principal is not None and principal.kind == "token" and principal.role == "operator"
    first_seen = service.store.get_token(created["id"])["last_used_at"]
    assert first_seen
    service.authenticate(_request(bearer=token))
    assert service.store.get_token(created["id"])["last_used_at"] == first_seen  # touched at most once a minute

    with pytest.raises(Forbidden):
        service.create_token(principal, "nested", None, None, CTX)  # tokens cannot create tokens
    with pytest.raises(Invalid):
        service.create_token(admin, "", None, None, CTX)
    with pytest.raises(Invalid):
        service.create_token(admin, "x", None, 0, CTX)

    # the owner's role caps the token's effective role even after a demotion
    viewer = service.create_user(admin, "viewer", PASSWORD, "V", "viewer", CTX)
    _v, viewer_cookie = service.login("viewer", PASSWORD, None, CTX)
    viewer_principal = service.authenticate(_request(cookie=viewer_cookie))
    assert viewer_principal is not None
    with pytest.raises(Forbidden):
        service.create_token(viewer_principal, "escalate", "admin", None, CTX)
    own = service.create_token(viewer_principal, "own", None, None, CTX)
    assert own["role"] == "viewer"
    assert [item["name"] for item in service.list_tokens(viewer_principal)] == ["own"]
    with pytest.raises(Forbidden):
        service.list_tokens(viewer_principal, include_all=True)
    assert {item["name"] for item in service.list_tokens(admin, include_all=True)} == {"ci", "own"}

    _sql(platform, "UPDATE api_tokens SET expires_at = ? WHERE id = ?", (iso(datetime.now(timezone.utc) - timedelta(minutes=1)), created["id"]))
    with pytest.raises(HTTPException) as expired:
        service.authenticate(_request(bearer=token))
    assert expired.value.status_code == 401 and "expired" in expired.value.detail

    service.update_user(admin, viewer["id"], disabled=True, ctx=CTX)
    with pytest.raises(HTTPException):
        service.authenticate(_request(bearer=own["token"]))
    service.update_user(admin, viewer["id"], disabled=False, ctx=CTX)
    assert service.authenticate(_request(bearer=own["token"])) is not None
    service.delete_token(admin, own["id"], CTX)  # admins may revoke anyone's token
    with pytest.raises(HTTPException):
        service.authenticate(_request(bearer=own["token"]))


# ── lockout ───────────────────────────────────────────────────────────────────


def test_lockout_counts_per_username(platform: Platform, service: AuthService) -> None:
    _setup(service)
    for _ in range(3):
        with pytest.raises(LoginFailed):
            service.login("admin", "nope nope nope", None, CTX)
    with pytest.raises(AccountLocked) as locked:
        service.login("admin", PASSWORD, None, CTX)
    assert 0 < locked.value.retry_after <= 15 * 60
    assert any(entry.action == "auth.locked" and entry.actor == "admin" for entry in platform.audit.iter_all())

    # failures age out of the window
    _sql(platform, "UPDATE login_attempts SET ts = ?", (iso(datetime.now(timezone.utc) - timedelta(minutes=16)),))
    user, _token = service.login("admin", PASSWORD, None, CTX)
    assert user["username"] == "admin"
    assert service.store.recent_failures("admin", timedelta(minutes=15)) == (0, None)


# ── MFA ───────────────────────────────────────────────────────────────────────


def test_mfa_secret_encrypted_totp_replay_and_recovery(platform: Platform, service: AuthService) -> None:
    _user, cookie = _setup(service)
    principal = service.authenticate(_request(cookie=cookie))
    assert principal is not None
    enrolment = service.mfa_enroll(principal, CTX)
    secret = enrolment["secret"]
    row = service.store.get_user(principal.user_id or "")
    assert row is not None and row["mfa_pending_secret"] != secret and row["mfa_secret_encrypted"] == 1
    assert platform.secrets.decrypt_json(row["mfa_pending_secret"]) == secret

    totp = pyotp.TOTP(secret)
    now = datetime.now(timezone.utc)
    with pytest.raises(Forbidden):
        service.mfa_confirm(principal, "000000", CTX)
    codes = service.mfa_confirm(principal, totp.at(now, -1), CTX)["recovery_codes"]
    assert len(codes) == 8 and len(set(codes)) == 8
    stored_codes = service.store.unused_recovery_codes(principal.user_id or "")
    assert len(stored_codes) == 8 and not any(code.replace("-", "") in str(stored_codes) for code in codes)

    with pytest.raises(MfaRequired):
        service.login("admin", PASSWORD, None, CTX)
    with pytest.raises(MfaRequired):
        service.login("admin", PASSWORD, "000000", CTX)
    current = totp.now()
    service.login("admin", PASSWORD, current, CTX)
    with pytest.raises(MfaRequired):
        service.login("admin", PASSWORD, current, CTX)  # replay of a used code
    service.login("admin", PASSWORD, codes[0], CTX)
    with pytest.raises(MfaRequired):
        service.login("admin", PASSWORD, codes[0], CTX)  # recovery codes are single use
    assert len(service.store.unused_recovery_codes(principal.user_id or "")) == 7

    with pytest.raises(Forbidden):
        service.mfa_disable(principal, "wrong wrong wrong", codes[1], CTX)
    service.mfa_disable(principal, PASSWORD, codes[1], CTX)
    row = service.store.get_user(principal.user_id or "")
    assert row is not None and row["mfa_enabled"] == 0 and row["mfa_secret"] is None
    assert service.store.unused_recovery_codes(principal.user_id or "") == []
    assert platform.audit.verify().ok


def test_mfa_secret_plaintext_without_key_then_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VMA_SECRET_KEY", raising=False)
    platform = Platform.from_config(_config(), db_path=tmp_path / "p.sqlite")
    service = platform.auth
    assert isinstance(service, AuthService) and not platform.secrets.available
    _user, cookie = _setup(service)
    principal = service.authenticate(_request(cookie=cookie))
    assert principal is not None
    secret = service.mfa_enroll(principal, CTX)["secret"]
    service.mfa_confirm(principal, pyotp.TOTP(secret).now(), CTX)
    row = service.store.get_user(principal.user_id or "")
    assert row is not None and row["mfa_secret"] == secret and row["mfa_secret_encrypted"] == 0
    checks = {check["id"]: check for check in posture_checks(platform, _request())}
    assert checks["mfa.secrets_encrypted"]["status"] == "fail" and checks["secrets.key"]["status"] == "fail"

    old_key = SecretBox.generate_key()
    platform.secrets = SecretBox([old_key])
    assert service.rotate_secrets() == 1  # plaintext row encrypted
    row = service.store.get_user(principal.user_id or "")
    assert row is not None and row["mfa_secret"] != secret and row["mfa_secret_encrypted"] == 1
    assert platform.secrets.decrypt_json(row["mfa_secret"]) == secret
    assert {check["id"]: check for check in posture_checks(platform, _request())}["mfa.secrets_encrypted"]["status"] == "pass"

    new_key = SecretBox.generate_key()
    platform.secrets = SecretBox([new_key, old_key])
    assert service.rotate_secrets() == 1
    platform.secrets = SecretBox([new_key])  # old key dropped
    row = service.store.get_user(principal.user_id or "")
    assert row is not None and platform.secrets.decrypt_json(row["mfa_secret"]) == secret
    service.login("admin", PASSWORD, pyotp.TOTP(secret).at(datetime.now(timezone.utc), 1), CTX)


def test_mfa_required_policy_and_oidc_users_exempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMA_SECRET_KEY", SecretBox.generate_key())
    platform = Platform.from_config(_config(mfa="required"), db_path=tmp_path / "p.sqlite")
    service = platform.auth
    assert isinstance(service, AuthService)
    _user, cookie = _setup(service)
    assert service.authenticate(_request("/api/auth/me", cookie=cookie)) is not None
    with pytest.raises(HTTPException) as blocked:
        service.authenticate(_request("/api/runs", cookie=cookie))
    assert blocked.value.status_code == 403 and blocked.value.detail == "mfa_enrollment_required"

    sso = service.store.create_user(username="sso@corp.example", name="S", role="viewer", password_hash=None, auth_kind="oidc", oidc_issuer="https://idp", oidc_subject="s1")
    assert service.mfa_enrollment_required(sso) is False
    payload = service.user_payload(sso)
    assert payload["mfa_enrollment_required"] is False and payload["auth_kind"] == "oidc"
    with pytest.raises(LoginFailed):
        service.login("sso@corp.example", PASSWORD, None, CTX)  # no password login for SSO accounts


# ── user administration ───────────────────────────────────────────────────────


def test_user_admin_rules(platform: Platform, service: AuthService) -> None:
    _user, cookie = _setup(service)
    admin = service.authenticate(_request(cookie=cookie))
    assert admin is not None and admin.user_id
    with pytest.raises(Invalid):
        service.create_user(admin, "bad user", PASSWORD, "x", "viewer", CTX)
    with pytest.raises(Invalid):
        service.create_user(admin, "bob", "short", "x", "viewer", CTX)
    with pytest.raises(Invalid):
        service.create_user(admin, "bob", PASSWORD, "x", "superuser", CTX)
    bob = service.create_user(admin, "Bob", PASSWORD, "Bob", "operator", CTX)
    assert bob["username"] == "bob" and bob["role"] == "operator"
    with pytest.raises(Conflict):
        service.create_user(admin, "BOB", PASSWORD, "Bob", "viewer", CTX)

    with pytest.raises(Conflict):
        service.update_user(admin, admin.user_id, role="viewer", ctx=CTX)  # last admin
    with pytest.raises(Conflict):
        service.delete_user(admin, admin.user_id, CTX)  # yourself
    with pytest.raises(Conflict):
        service.update_user(admin, admin.user_id, disabled=True, ctx=CTX)

    service.update_user(admin, bob["id"], role="admin", ctx=CTX)
    service.update_user(admin, admin.user_id, role="operator", ctx=CTX)  # now allowed: bob is an admin
    assert service.get_user(admin.user_id)["role"] == "operator"
    _b, bob_cookie = service.login("bob", PASSWORD, None, CTX)
    bob_principal = service.authenticate(_request(cookie=bob_cookie))
    assert bob_principal is not None
    with pytest.raises(Conflict):
        service.delete_user(bob_principal, bob["id"], CTX)
    service.update_user(bob_principal, admin.user_id, password="a brand new passphrase!", ctx=CTX)
    with pytest.raises(HTTPException):
        service.authenticate(_request(cookie=cookie))  # password reset revoked the sessions
    service.login("admin", "a brand new passphrase!", None, CTX)
    service.delete_user(bob_principal, admin.user_id, CTX)
    assert [user["username"] for user in service.list_users()] == ["bob"]
    assert platform.audit.verify().ok


# ── retention ─────────────────────────────────────────────────────────────────


class _FakeRuntime:
    def __init__(self, records: list[SimpleNamespace]) -> None:
        self.records = records
        self.deleted: list[str] = []

    def list_runs(self) -> list[SimpleNamespace]:
        return list(self.records)

    def delete_run(self, run_id: str) -> None:
        self.deleted.append(run_id)
        self.records = [record for record in self.records if record.run_id != run_id]


def _record(run_id: str, status: str, days_old: int) -> SimpleNamespace:
    stamp = iso(datetime.now(timezone.utc) - timedelta(days=days_old))
    return SimpleNamespace(run_id=run_id, status=status, created_at=stamp, updated_at=stamp)


def test_retention_sweep_runs_and_audit(platform: Platform) -> None:
    runtime = _FakeRuntime([
        _record("old-ok", "succeeded", 45), _record("old-paused", "paused", 45), _record("old-running", "running", 45),
        _record("old-failed", "failed", 31), _record("fresh", "succeeded", 2),
    ])
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(timespec="milliseconds")
    platform.audit.record("ancient.event")
    _sql(platform, "UPDATE audit_log SET ts = ? WHERE action = 'ancient.event'", (old_ts,))
    platform.audit.record("recent.event")

    preview = sweep(platform, runtime, dry_run=True)
    assert preview == {"runs_deleted": 2, "audit_pruned": 1} and runtime.deleted == []
    assert not any(entry.action == "retention.sweep" for entry in platform.audit.iter_all())

    result = sweep(platform, runtime)
    assert result == {"runs_deleted": 2, "audit_pruned": 1}
    assert sorted(runtime.deleted) == ["old-failed", "old-ok"]
    assert {record.run_id for record in runtime.records} == {"old-paused", "old-running", "fresh"}
    actions = [entry.action for entry in platform.audit.iter_all()]
    assert "ancient.event" not in actions and "audit.pruned" in actions and "retention.sweep" in actions
    assert platform.audit.verify().ok  # the chain was re-anchored after pruning

    assert sweep(platform, runtime, runs_days=1, include_audit=False) == {"runs_deleted": 1, "audit_pruned": 0}
    assert {record.run_id for record in runtime.records} == {"old-paused", "old-running"}  # never touched


def test_retention_disabled_by_default(tmp_path: Path) -> None:
    platform = Platform.from_config({}, db_path=tmp_path / "p.sqlite")
    runtime = _FakeRuntime([_record("old", "succeeded", 400)])
    assert sweep(platform, runtime) == {"runs_deleted": 0, "audit_pruned": 0} and runtime.deleted == []


# ── rate limiter and posture ──────────────────────────────────────────────────


def test_token_bucket_limiter() -> None:
    limiter = TokenBucketLimiter(rate_per_minute=3)
    assert [limiter.acquire("1.2.3.4", now=100.0)[0] for _ in range(3)] == [True, True, True]
    allowed, retry_after = limiter.acquire("1.2.3.4", now=100.0)
    assert not allowed and retry_after >= 1
    assert limiter.acquire("5.6.7.8", now=100.0)[0]  # other clients are independent
    assert limiter.acquire("1.2.3.4", now=121.0)[0]  # one token refilled after 20 s
    assert not limiter.acquire("1.2.3.4", now=121.0)[0]


def test_posture_checks_shape(platform: Platform, service: AuthService) -> None:
    _setup(service)
    checks = posture_checks(platform, _request(https=True))
    by_id = {check["id"]: check for check in checks}
    assert by_id["transport.tls"]["status"] == "pass" and by_id["auth.enforced"]["status"] == "pass"
    assert by_id["retention.runs"]["status"] == "pass" and by_id["retention.audit"]["status"] == "pass"
    assert by_id["mfa.policy"]["status"] == "warn" and by_id["mfa.coverage"]["status"] == "warn"
    assert by_id["auth.lockout"]["status"] == "pass" and by_id["session.lifetime"]["status"] == "pass"
    assert by_id["oidc.configured"]["status"] == "warn" and by_id["deploy.allow_destroy"]["status"] == "warn"
    assert all(check["frameworks"] for check in checks)


# ── store details ─────────────────────────────────────────────────────────────


def test_store_oidc_state_single_use_and_expiry(platform: Platform) -> None:
    store = SecurityStore(platform.db)
    store.save_oidc_state("s1", "n1", "v1", "https://app/cb", ttl=timedelta(minutes=10))
    row = store.pop_oidc_state("s1")
    assert row is not None and row["nonce"] == "n1" and row["code_verifier"] == "v1"
    assert store.pop_oidc_state("s1") is None  # consumed
    store.save_oidc_state("s2", "n2", "v2", "https://app/cb", ttl=timedelta(minutes=-1))
    assert store.pop_oidc_state("s2") is None  # expired
    with pytest.raises(sqlite3.IntegrityError):
        store.create_user(username="dup", name="", role="viewer", password_hash=None)
        store.create_user(username="DUP", name="", role="viewer", password_hash=None)


# ── CLI ───────────────────────────────────────────────────────────────────────


def test_cli_admin_secrets_audit_and_prune(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VMA_SECRET_KEY", SecretBox.generate_key())
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "target_cloud": "aws",
            "generation": {"mode": "deterministic"},
            "mcp": {"enabled": False},
            "logging": {"level": "WARNING", "detailed_log_file": None},
            "runtime": {"runs_dir": str(tmp_path / "runs"), "checkpoint_db": "", "platform_db": str(tmp_path / "platform.sqlite")},
            "security": {"auth": {"mode": "required"}, "retention": {"runs_days": 0, "audit_days": 0}},
        }),
        encoding="utf-8",
    )
    runner = CliRunner()
    args = ["--config", str(config_path)]

    created = runner.invoke(cli, ["admin", "create-user", "Alice", "--role", "admin", "--name", "Alice", "--password", PASSWORD, *args])
    assert created.exit_code == 0, created.output
    assert "created alice (admin)" in created.output
    weak = runner.invoke(cli, ["admin", "create-user", "bob", "--password", "short", *args])
    assert weak.exit_code != 0 and "12" in weak.output
    listed = runner.invoke(cli, ["admin", "list-users", *args])
    assert listed.exit_code == 0 and "alice" in listed.output and "admin" in listed.output
    role = runner.invoke(cli, ["admin", "set-role", "alice", "viewer", *args])
    assert role.exit_code != 0 and "last admin" in role.output
    runner.invoke(cli, ["admin", "create-user", "bob", "--role", "admin", "--password", PASSWORD, *args])
    role = runner.invoke(cli, ["admin", "set-role", "alice", "operator", *args])
    assert role.exit_code == 0 and "alice is now operator" in role.output
    reset = runner.invoke(cli, ["admin", "reset-password", "alice", "--password", "a brand new passphrase!", *args])
    assert reset.exit_code == 0 and "password updated" in reset.output
    missing = runner.invoke(cli, ["admin", "reset-password", "nobody", "--password", PASSWORD, *args])
    assert missing.exit_code != 0 and "no user named nobody" in missing.output

    key = runner.invoke(cli, ["secrets", "generate-key"])
    assert key.exit_code == 0 and len(key.output.strip()) == 44
    rotated = runner.invoke(cli, ["secrets", "rotate", *args])
    assert rotated.exit_code == 0 and "auth: 0 row(s)" in rotated.output and "rotated 0 row(s)" in rotated.output

    verify = runner.invoke(cli, ["audit", "verify", *args])
    assert verify.exit_code == 0 and verify.output.startswith("OK:")

    prune = runner.invoke(cli, ["runs", "prune", "--older-than-days", "30", "--dry-run", *args])
    assert prune.exit_code == 0 and "would delete 0 run(s)" in prune.output
    prune = runner.invoke(cli, ["runs", "prune", "--older-than-days", "30", *args])
    assert prune.exit_code == 0 and "deleted 0 run(s)" in prune.output

    platform = Platform.from_config(yaml.safe_load(config_path.read_text(encoding="utf-8")))
    actions = [entry.action for entry in platform.audit.iter_all()]
    assert {"user.created", "user.updated", "secrets.rotated"} <= set(actions)
    assert all(entry.actor == "cli" for entry in platform.audit.iter_all() if entry.action.startswith("user."))
    assert platform.audit.verify().ok
