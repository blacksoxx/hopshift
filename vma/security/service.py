"""AuthService: local accounts, sessions, API tokens, RBAC, TOTP MFA, OIDC sign-in, lockout.

Rules this module enforces everywhere:
- credentials are only ever stored hashed (argon2id for passwords, sha256 for the random
  session / API tokens and recovery codes) and TOTP secrets are encrypted when a key exists;
- unknown users and wrong passwords produce the same response after the same argon2 work;
- usernames are trimmed and case-insensitive; timestamps are ISO 8601 UTC;
- every security event is written to the hash-chained audit log with actor, ip and user agent.
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
from datetime import timedelta
from typing import Any

import pyotp
from fastapi import HTTPException, Request, Response
from loguru import logger

from api.deps import ROLE_ORDER, Principal
from api.middleware import SESSION_COOKIE, is_https
from vma.errors import Conflict, Forbidden, Invalid, NotFound, PlatformError
from vma.security import passwords
from vma.security.oidc import STATE_TTL_MINUTES, OIDCClient, OIDCConfig, pkce_pair
from vma.security.ratelimit import RateLimitMiddleware, TokenBucketLimiter
from vma.security.retention import start_background_sweeper, stop_background_sweeper
from vma.security.store import (
    SecurityStore,
    iso,
    normalize_username,
    now_iso,
    parse_iso,
    sha256_hex,
    utc_now,
)

TOKEN_PREFIX = "vma_"
TOTP_ISSUER = "vmware-migration-agent"
TOUCH_INTERVAL = timedelta(minutes=1)
RECOVERY_CODE_COUNT = 8
TOTP_STEP_SECONDS = 30
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{1,63}$")
ROLES: tuple[str, ...] = tuple(ROLE_ORDER)
AUTH_PATH_PREFIX = "/api/auth"
CLI_PRINCIPAL = Principal(subject="cli", kind="system", role="admin", name="command line")


class AuthError(Exception):
    """Login outcomes that the auth router maps to specific responses."""


class LoginFailed(AuthError):
    """Unknown user, wrong password or disabled account: one generic 401."""


class MfaRequired(AuthError):
    """Password accepted but a valid second factor is missing."""


class AccountLocked(AuthError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("account temporarily locked")
        self.retry_after = max(1, int(retry_after))


def _lower_role(first: str, second: str) -> str:
    return first if ROLE_ORDER.get(first, -1) <= ROLE_ORDER.get(second, -1) else second


class AuthService:
    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.store = SecurityStore(platform.db)
        auth_cfg = self._file_auth_cfg()
        self.oidc_config = OIDCConfig(auth_cfg.get("oidc"))
        self.oidc: OIDCClient | None = None
        if self.oidc_config.configured:
            self.oidc = OIDCClient(self.oidc_config, client_secret=lambda: os.environ.get(self.oidc_config.client_secret_env))
        try:
            rate = float(auth_cfg.get("login_rate_per_minute") or 20)
        except (TypeError, ValueError):
            rate = 20.0
        self.limiter = TokenBucketLimiter(rate_per_minute=max(1.0, rate))

    # ── configuration ─────────────────────────────────────────────────────────

    def _file_auth_cfg(self) -> dict[str, Any]:
        security = self.platform.config.get("security") if isinstance(self.platform.config.get("security"), dict) else {}
        auth = security.get("auth") if isinstance(security.get("auth"), dict) else {}
        return auth

    def auth_config(self) -> dict[str, Any]:
        """The effective auth section (config.yaml with the editable overlay applied)."""
        config = self.platform.effective_config()
        security = config.get("security") if isinstance(config.get("security"), dict) else {}
        auth = security.get("auth") if isinstance(security.get("auth"), dict) else {}
        return auth

    def _int_setting(self, auth: dict[str, Any], key: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(auth.get(key, default)))
        except (TypeError, ValueError):
            return default

    @property
    def session_lifetime(self) -> timedelta:
        return timedelta(hours=self._int_setting(self.auth_config(), "session_hours", 12, minimum=1))

    @property
    def idle_timeout(self) -> timedelta:
        return timedelta(minutes=self._int_setting(self.auth_config(), "idle_minutes", 60, minimum=1))

    @property
    def mfa_policy(self) -> str:
        return "required" if str(self.auth_config().get("mfa") or "optional").lower() == "required" else "optional"

    def lockout_settings(self) -> tuple[int, int]:
        auth = self.auth_config()
        return self._int_setting(auth, "lockout_threshold", 5), self._int_setting(auth, "lockout_minutes", 15)

    # ── app integration ───────────────────────────────────────────────────────

    def install_middleware(self, app: Any) -> None:
        """Rate limiting for the credential endpoints plus the hourly retention sweeper, which
        starts with the app (lifespan startup) so tests that never start the app spawn no thread."""
        app.add_middleware(RateLimitMiddleware, limiter=self.limiter)
        router = getattr(app, "router", None)
        on_startup = getattr(router, "on_startup", None)
        on_shutdown = getattr(router, "on_shutdown", None)
        if isinstance(on_startup, list) and isinstance(on_shutdown, list):
            on_startup.append(lambda: start_background_sweeper(app))
            on_shutdown.append(lambda: stop_background_sweeper(app))
            return
        add_event_handler = getattr(app, "add_event_handler", None)  # Starlette < 1.0
        if callable(add_event_handler):
            add_event_handler("startup", lambda: start_background_sweeper(app))
            add_event_handler("shutdown", lambda: stop_background_sweeper(app))

    # ── audit helper ──────────────────────────────────────────────────────────

    def _audit(
        self,
        action: str,
        *,
        actor: str,
        actor_kind: str = "user",
        target_type: str | None = None,
        target_id: str | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        ctx = ctx or {}
        self.platform.audit.record(
            action, actor=actor or "-", actor_kind=actor_kind, target_type=target_type, target_id=target_id,
            outcome=outcome, details=details or {}, ip=ctx.get("ip"), user_agent=ctx.get("user_agent"),
        )

    # ── payloads ──────────────────────────────────────────────────────────────

    def mfa_enrollment_required(self, user: dict[str, Any]) -> bool:
        return self.mfa_policy == "required" and user.get("auth_kind") == "password" and not bool(user.get("mfa_enabled"))

    def user_payload(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "role": user["role"],
            "auth_kind": user["auth_kind"],
            "disabled": bool(user["disabled"]),
            "mfa_enabled": bool(user["mfa_enabled"]),
            "mfa_enrollment_required": self.mfa_enrollment_required(user),
            "email": user.get("email"),
            "created_at": user["created_at"],
            "updated_at": user["updated_at"],
            "last_login_at": user.get("last_login_at"),
        }

    @staticmethod
    def token_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "prefix": row["prefix"],
            "role": row["role"],
            "user_id": row["user_id"],
            "username": row.get("username"),
            "created_at": row["created_at"],
            "expires_at": row.get("expires_at"),
            "last_used_at": row.get("last_used_at"),
        }

    def _principal(self, user: dict[str, Any], kind: str, role: str | None = None, mfa: bool | None = None) -> Principal:
        if mfa is None:
            mfa = bool(user["mfa_enabled"]) or user["auth_kind"] == "oidc"  # the IdP owns MFA for SSO accounts
        return Principal(subject=user["username"], kind=kind, role=role or user["role"], user_id=user["id"], name=user["name"], mfa=mfa)

    def _user_of(self, principal: Principal) -> dict[str, Any]:
        user = self.store.get_user(principal.user_id) if principal.user_id else None
        if user is None:
            raise NotFound("user not found")
        return user

    @staticmethod
    def _require_session(principal: Principal) -> None:
        if principal.kind != "user":
            raise Forbidden("this action requires an interactive session, not an API token")

    @staticmethod
    def validate_username(username: str) -> str:
        value = normalize_username(username)
        if not USERNAME_RE.match(value):
            raise Invalid("username must be 2-64 characters: letters, digits, '.', '_', '@', '+', '-'")
        return value

    @staticmethod
    def validate_role(role: str | None, default: str = "viewer") -> str:
        value = (role or default).strip().lower()
        if value not in ROLE_ORDER:
            raise Invalid(f"role must be one of {', '.join(ROLES)}")
        return value

    # ── authentication (every request) ────────────────────────────────────────

    def authenticate(self, request: Request) -> Principal | None:
        """Bearer API token first, then the session cookie. None when no credential is present;
        401 when one is present but invalid; 403 when MFA enrolment is required outside /auth."""
        header = request.headers.get("authorization")
        if header:
            scheme, _, value = header.partition(" ")
            value = value.strip()
            if scheme.lower() != "bearer" or not value:
                raise HTTPException(status_code=401, detail="invalid Authorization header")
            principal, user = self._authenticate_token(value)
        else:
            cookie = request.cookies.get(SESSION_COOKIE)
            if not cookie:
                return None
            principal, user = self._authenticate_session(cookie, request)
        if self.mfa_enrollment_required(user) and not request.url.path.startswith(AUTH_PATH_PREFIX):
            raise HTTPException(status_code=403, detail="mfa_enrollment_required")
        return principal

    def _authenticate_token(self, value: str) -> tuple[Principal, dict[str, Any]]:
        invalid = HTTPException(status_code=401, detail="invalid API token")
        if not value.startswith(TOKEN_PREFIX):
            raise invalid
        token = self.store.get_token_by_hash(sha256_hex(value))
        if token is None or token["revoked_at"]:
            raise invalid
        expires = parse_iso(token["expires_at"])
        if expires is not None and expires <= utc_now():
            raise HTTPException(status_code=401, detail="API token expired")
        user = self.store.get_user(token["user_id"])
        if user is None or user["disabled"]:
            raise invalid
        last_used = parse_iso(token["last_used_at"])
        if last_used is None or utc_now() - last_used >= TOUCH_INTERVAL:
            self.store.touch_token(token["id"])
        role = _lower_role(token["role"], user["role"])
        return self._principal(user, "token", role=role), user

    def _authenticate_session(self, cookie: str, request: Request) -> tuple[Principal, dict[str, Any]]:
        invalid = HTTPException(status_code=401, detail="session is not valid")
        session = self.store.get_session_by_hash(sha256_hex(cookie))
        if session is None or session["revoked_at"]:
            raise invalid
        now = utc_now()
        expires = parse_iso(session["expires_at"])
        if expires is None or expires <= now:
            self.store.revoke_session(session["id"])
            raise HTTPException(status_code=401, detail="session expired")
        last_seen = parse_iso(session["last_seen_at"]) or now
        if now - last_seen > self.idle_timeout:
            self.store.revoke_session(session["id"])
            raise HTTPException(status_code=401, detail="session expired after inactivity")
        user = self.store.get_user(session["user_id"])
        if user is None or user["disabled"]:
            self.store.revoke_session(session["id"])
            raise invalid
        if now - last_seen >= TOUCH_INTERVAL:
            self.store.touch_session(session["id"])
        request.state.session_id = session["id"]
        mfa = bool(user["mfa_enabled"]) or session["auth_method"] == "oidc"
        return self._principal(user, "user", mfa=mfa), user

    # ── status and setup ──────────────────────────────────────────────────────

    def setup_required(self) -> bool:
        return self.store.count_users() == 0

    def status(self, request: Request) -> dict[str, Any]:
        user_payload = None
        try:
            principal = self.authenticate(request)
        except HTTPException:
            principal = None
        if principal is not None and principal.user_id:
            user = self.store.get_user(principal.user_id)
            if user is not None:
                user_payload = self.user_payload(user)
                user_payload["principal"] = principal.to_dict()
        return {
            "setup_required": self.setup_required(),
            "auth_mode": "required",
            "oidc_enabled": self.oidc is not None,
            "mfa_policy": self.mfa_policy,
            "user": user_payload,
        }

    def setup(self, username: str, password: str, name: str, ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """Create the first admin while no users exist and open a session for them."""
        if not self.setup_required():
            raise Conflict("setup has already been completed")
        username = self.validate_username(username)
        passwords.validate_password(password, username)
        user = self.store.create_first_user(username=username, name=(name or "").strip()[:120] or username, password_hash=passwords.hash_password(password))
        if user is None:
            raise Conflict("setup has already been completed")
        self._audit("auth.setup", actor=username, target_type="user", target_id=user["id"], details={"role": "admin"}, ctx=ctx)
        token = self._create_session(user, ctx, auth_method="password")
        user = self.store.update_user(user["id"], last_login_at=now_iso()) or user
        return self.user_payload(user), token

    # ── login, lockout, logout ────────────────────────────────────────────────

    def login(self, username: str, password: str, totp_code: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        username = normalize_username(username)
        self._check_lockout(username, ctx)
        user = self.store.get_user_by_username(username) if username else None
        usable = user is not None and user["auth_kind"] == "password" and not user["disabled"]
        password_hash = user["password_hash"] if usable and user is not None else None
        if not passwords.verify_password(password_hash, password or "") or user is None:
            reason = "unknown_user" if user is None else "disabled" if user["disabled"] else "sso_account" if user["auth_kind"] != "password" else "bad_password"
            self._register_failure(username, ctx, reason)
            raise LoginFailed()
        if user["mfa_enabled"]:
            if not (totp_code or "").strip():
                raise MfaRequired()
            if not self._verify_second_factor(user, totp_code or "", ctx):
                self._register_failure(username, ctx, "mfa_invalid")
                raise MfaRequired()
            user = self.store.get_user(user["id"]) or user
        if user["password_hash"] and passwords.needs_rehash(user["password_hash"]):
            self.store.update_user(user["id"], password_hash=passwords.hash_password(password))
        self.store.clear_attempts(username)
        token = self._create_session(user, ctx, auth_method="password+totp" if user["mfa_enabled"] else "password")
        user = self.store.update_user(user["id"], last_login_at=now_iso()) or user
        self._audit("auth.login", actor=username, target_type="user", target_id=user["id"], details={"mfa": bool(user["mfa_enabled"])}, ctx=ctx)
        return self.user_payload(user), token

    def _check_lockout(self, username: str, ctx: dict[str, Any]) -> None:
        threshold, minutes = self.lockout_settings()
        if threshold <= 0 or minutes <= 0 or not username:
            return
        failures, latest = self.store.recent_failures(username, timedelta(minutes=minutes))
        if failures < threshold:
            return
        latest_at = parse_iso(latest) or utc_now()
        retry_after = int((latest_at + timedelta(minutes=minutes) - utc_now()).total_seconds())
        self._audit("auth.login", actor=username, actor_kind="anonymous", outcome="denied", details={"reason": "locked"}, ctx=ctx)
        raise AccountLocked(retry_after)

    def _register_failure(self, username: str, ctx: dict[str, Any], reason: str) -> None:
        self.store.record_attempt(username, ctx.get("ip"), False)
        self._audit("auth.login", actor=username or "-", actor_kind="anonymous", outcome="failure", details={"reason": reason}, ctx=ctx)
        threshold, minutes = self.lockout_settings()
        if threshold <= 0 or minutes <= 0 or not username:
            return
        failures, _ = self.store.recent_failures(username, timedelta(minutes=minutes))
        if failures == threshold:
            logger.warning("auth: account {} locked for {} min after {} failed logins", username, minutes, failures)
            self._audit("auth.locked", actor=username, actor_kind="anonymous", outcome="denied", details={"failures": failures, "minutes": minutes}, ctx=ctx)

    def logout(self, request: Request, principal: Principal | None, ctx: dict[str, Any]) -> None:
        """Revoke the session named by the cookie (even an expired one); audit when the caller was known."""
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie:
            session = self.store.get_session_by_hash(sha256_hex(cookie))
            if session is not None:
                self.store.revoke_session(session["id"])
        if principal is not None:
            self._audit("auth.logout", actor=principal.subject, actor_kind=principal.kind, target_type="user", target_id=principal.user_id, ctx=ctx)

    # ── sessions and cookies ──────────────────────────────────────────────────

    def _create_session(self, user: dict[str, Any], ctx: dict[str, Any], *, auth_method: str) -> str:
        raw = secrets.token_urlsafe(32)
        self.store.create_session(
            user["id"], sha256_hex(raw), lifetime=self.session_lifetime, ip=ctx.get("ip"), user_agent=ctx.get("user_agent"),
            auth_method=auth_method,
        )
        return raw

    def set_session_cookie(self, response: Response, request: Request, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE, token, max_age=int(self.session_lifetime.total_seconds()), path="/", httponly=True,
            samesite="lax", secure=is_https(request),
        )

    @staticmethod
    def clear_session_cookie(response: Response, request: Request) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=is_https(request))

    # ── profile ───────────────────────────────────────────────────────────────

    def me(self, principal: Principal) -> dict[str, Any]:
        payload = self.user_payload(self._user_of(principal))
        payload["principal"] = principal.to_dict()
        return payload

    def change_password(self, principal: Principal, request: Request, current_password: str, new_password: str, ctx: dict[str, Any]) -> None:
        self._require_session(principal)
        user = self._user_of(principal)
        if user["auth_kind"] != "password":
            raise Invalid("this account signs in through single sign-on and has no local password")
        if not passwords.verify_password(user["password_hash"], current_password or ""):
            self._audit("auth.password_changed", actor=user["username"], target_type="user", target_id=user["id"], outcome="failure", details={"reason": "bad_current_password"}, ctx=ctx)
            raise Forbidden("current password is incorrect")
        passwords.validate_password(new_password, user["username"])
        if hmac.compare_digest(new_password, current_password or ""):
            raise Invalid("the new password must differ from the current one")
        self.store.update_user(user["id"], password_hash=passwords.hash_password(new_password), password_changed_at=now_iso())
        revoked = self.store.revoke_user_sessions(user["id"], keep_session_id=getattr(request.state, "session_id", None))
        self._audit("auth.password_changed", actor=user["username"], target_type="user", target_id=user["id"], details={"other_sessions_revoked": revoked}, ctx=ctx)

    # ── MFA ───────────────────────────────────────────────────────────────────

    def _encrypt_secret(self, secret: str) -> tuple[str, int]:
        box = self.platform.secrets
        if box.available:
            return box.encrypt_json(secret), 1
        logger.warning("auth: {} is not set; storing a TOTP secret unencrypted (flagged in the posture report)", box.env_var)
        return secret, 0

    def _decrypt_secret(self, stored: str | None, encrypted: Any) -> str | None:
        if not stored:
            return None
        if int(encrypted or 0):
            value = self.platform.secrets.decrypt_json(stored)
            return str(value) if value else None
        return stored

    def _verify_totp(self, user: dict[str, Any], secret: str, code: str) -> bool:
        """RFC 6238 with a one-step window on each side; a code (or an earlier step) never verifies twice."""
        totp = pyotp.TOTP(secret)
        now = utc_now()
        current_step = int(now.timestamp()) // TOTP_STEP_SECONDS
        last_step = user.get("mfa_last_step")
        matched: int | None = None
        for offset in (0, -1, 1):
            if hmac.compare_digest(totp.at(now, offset), code):
                matched = current_step + offset
        if matched is None:
            return False
        if last_step is not None and matched <= int(last_step):
            return False
        self.store.update_user(user["id"], mfa_last_step=matched)
        return True

    def _verify_second_factor(self, user: dict[str, Any], code: str, ctx: dict[str, Any]) -> bool:
        cleaned = code.strip().replace(" ", "")
        secret = self._decrypt_secret(user.get("mfa_secret"), user.get("mfa_secret_encrypted"))
        if secret and cleaned.isdigit() and len(cleaned) == 6 and self._verify_totp(user, secret, cleaned):
            return True
        normalized = cleaned.lower().replace("-", "")
        if len(normalized) >= 10:
            matched: dict[str, Any] | None = None
            for row in self.store.unused_recovery_codes(user["id"]):  # full scan: constant iterations
                # recovery codes are short enough to brute-force from a leaked table, so they are
                # stored with the same slow hash as passwords (argon2id), never a fast digest
                if passwords.verify_password(row["code_hash"], normalized):
                    matched = row
            if matched is not None and self.store.use_recovery_code(int(matched["id"])):
                remaining = len(self.store.unused_recovery_codes(user["id"]))
                self._audit("auth.recovery_code_used", actor=user["username"], target_type="user", target_id=user["id"], details={"remaining": remaining}, ctx=ctx)
                return True
        return False

    def mfa_enroll(self, principal: Principal, ctx: dict[str, Any]) -> dict[str, Any]:
        self._require_session(principal)
        user = self._user_of(principal)
        if user["auth_kind"] != "password":
            raise Invalid("MFA for single sign-on accounts is managed by the identity provider")
        if user["mfa_enabled"]:
            raise Conflict("MFA is already enabled; disable it before enrolling again")
        secret = pyotp.random_base32()
        stored, encrypted = self._encrypt_secret(secret)
        self.store.update_user(user["id"], mfa_pending_secret=stored, mfa_secret_encrypted=encrypted)
        self._audit("auth.mfa_enrolled", actor=user["username"], target_type="user", target_id=user["id"], details={"encrypted": bool(encrypted)}, ctx=ctx)
        return {"secret": secret, "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name=TOTP_ISSUER)}

    def mfa_confirm(self, principal: Principal, code: str, ctx: dict[str, Any]) -> dict[str, Any]:
        self._require_session(principal)
        user = self._user_of(principal)
        pending = user.get("mfa_pending_secret")
        if not pending:
            raise Invalid("no MFA enrolment in progress; call /auth/mfa/enroll first")
        secret = self._decrypt_secret(pending, user.get("mfa_secret_encrypted"))
        cleaned = (code or "").strip().replace(" ", "")
        fresh = {**user, "mfa_last_step": None}  # the enrolment code counts as the first used step
        if not secret or not (cleaned.isdigit() and len(cleaned) == 6 and self._verify_totp(fresh, secret, cleaned)):
            self._audit("auth.mfa_confirmed", actor=user["username"], target_type="user", target_id=user["id"], outcome="failure", ctx=ctx)
            raise Forbidden("the code is not valid for the enrolled authenticator")
        codes = [f"{secrets.token_hex(5)[:5]}-{secrets.token_hex(5)[:5]}" for _ in range(RECOVERY_CODE_COUNT)]
        self.store.replace_recovery_codes(user["id"], [passwords.hash_password(item.replace("-", "")) for item in codes])
        self.store.update_user(user["id"], mfa_secret=pending, mfa_pending_secret=None, mfa_enabled=1)
        self._audit("auth.mfa_confirmed", actor=user["username"], target_type="user", target_id=user["id"], details={"recovery_codes": RECOVERY_CODE_COUNT}, ctx=ctx)
        return {"recovery_codes": codes}

    def mfa_disable(self, principal: Principal, password: str, code: str, ctx: dict[str, Any]) -> None:
        self._require_session(principal)
        user = self._user_of(principal)
        if not user["mfa_enabled"]:
            raise Invalid("MFA is not enabled on this account")
        if not passwords.verify_password(user["password_hash"], password or ""):
            raise Forbidden("password is incorrect")
        if not self._verify_second_factor(user, code or "", ctx):
            raise Forbidden("the code is not valid")
        self._clear_mfa(user["id"])
        self._audit("auth.mfa_disabled", actor=user["username"], target_type="user", target_id=user["id"], ctx=ctx)

    def mfa_reset(self, actor: Principal, user_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise NotFound("user not found")
        self._clear_mfa(user_id)
        self.store.revoke_user_sessions(user_id)
        self._audit("auth.mfa_reset", actor=actor.subject, actor_kind=actor.kind, target_type="user", target_id=user_id, details={"username": user["username"]}, ctx=ctx)
        return self.user_payload(self.store.get_user(user_id) or user)

    def _clear_mfa(self, user_id: str) -> None:
        self.store.update_user(user_id, mfa_secret=None, mfa_pending_secret=None, mfa_enabled=0, mfa_last_step=None, mfa_secret_encrypted=0)
        self.store.delete_recovery_codes(user_id)

    # ── API tokens ────────────────────────────────────────────────────────────

    def list_tokens(self, principal: Principal, include_all: bool = False) -> list[dict[str, Any]]:
        if include_all and principal.role != "admin":
            raise Forbidden("admin role required to list every token")
        rows = self.store.list_tokens(None if include_all else principal.user_id)
        return [self.token_payload(row) for row in rows]

    def create_token(self, principal: Principal, name: str, role: str | None, expires_days: int | None, ctx: dict[str, Any]) -> dict[str, Any]:
        self._require_session(principal)
        user = self._user_of(principal)
        if self.mfa_enrollment_required(user):
            raise Forbidden("mfa_enrollment_required")
        cleaned = (name or "").strip()
        if not cleaned or len(cleaned) > 80:
            raise Invalid("token name must be 1-80 characters")
        token_role = self.validate_role(role, default=principal.role)
        if ROLE_ORDER[token_role] > ROLE_ORDER.get(principal.role, -1):
            raise Forbidden("a token's role must not exceed your own role")
        expires_at: str | None = None
        if expires_days is not None:
            if not 1 <= int(expires_days) <= 3650:
                raise Invalid("expires_days must be between 1 and 3650")
            expires_at = iso(utc_now() + timedelta(days=int(expires_days)))
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        row = self.store.create_token(user_id=user["id"], name=cleaned, token_hash=sha256_hex(raw), prefix=raw[:12], role=token_role, expires_at=expires_at)
        self._audit("auth.token_created", actor=principal.subject, actor_kind=principal.kind, target_type="api_token", target_id=row["id"], details={"name": cleaned, "role": token_role, "expires_at": expires_at}, ctx=ctx)
        payload = self.token_payload({**row, "username": user["username"]})
        payload["token"] = raw
        return payload

    def delete_token(self, principal: Principal, token_id: str, ctx: dict[str, Any]) -> None:
        row = self.store.get_token(token_id)
        if row is None or row["revoked_at"] or (row["user_id"] != principal.user_id and principal.role != "admin"):
            raise NotFound("token not found")
        self.store.revoke_token(token_id)
        self._audit("auth.token_deleted", actor=principal.subject, actor_kind=principal.kind, target_type="api_token", target_id=token_id, details={"name": row["name"], "owner": row["user_id"]}, ctx=ctx)

    # ── user administration ───────────────────────────────────────────────────

    def list_users(self) -> list[dict[str, Any]]:
        return [self.user_payload(user) for user in self.store.list_users()]

    def get_user(self, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise NotFound("user not found")
        return self.user_payload(user)

    def find_user(self, username: str) -> dict[str, Any]:
        user = self.store.get_user_by_username(username)
        if user is None:
            raise NotFound(f"no user named {normalize_username(username)}")
        return user

    def create_user(self, actor: Principal, username: str, password: str, name: str, role: str, ctx: dict[str, Any]) -> dict[str, Any]:
        username = self.validate_username(username)
        role = self.validate_role(role)
        if self.store.get_user_by_username(username) is not None:
            raise Conflict("a user with this username already exists")
        passwords.validate_password(password, username)
        user = self.store.create_user(username=username, name=(name or "").strip()[:120] or username, role=role, password_hash=passwords.hash_password(password))
        self._audit("user.created", actor=actor.subject, actor_kind=actor.kind, target_type="user", target_id=user["id"], details={"username": username, "role": role}, ctx=ctx)
        return self.user_payload(user)

    def update_user(
        self,
        actor: Principal,
        user_id: str,
        *,
        name: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
        password: str | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise NotFound("user not found")
        changes: dict[str, Any] = {}
        is_active_admin = user["role"] == "admin" and not user["disabled"]
        if role is not None:
            new_role = self.validate_role(role)
            if new_role != user["role"]:
                if is_active_admin and self.store.count_admins(exclude_id=user_id) == 0:
                    raise Conflict("cannot demote the last admin")
                changes["role"] = new_role
        if disabled is not None and bool(disabled) != bool(user["disabled"]):
            if disabled and user_id == actor.user_id:
                raise Conflict("you cannot disable your own account")
            if disabled and is_active_admin and self.store.count_admins(exclude_id=user_id) == 0:
                raise Conflict("cannot disable the last admin")
            changes["disabled"] = 1 if disabled else 0
        if password is not None:
            if user["auth_kind"] != "password":
                raise Invalid("single sign-on accounts have no local password")
            passwords.validate_password(password, user["username"])
            changes["password_hash"] = passwords.hash_password(password)
            changes["password_changed_at"] = now_iso()
        if name is not None:
            changes["name"] = name.strip()[:120] or user["username"]
        if not changes:
            return self.user_payload(user)
        updated = self.store.update_user(user_id, **changes) or user
        if "password_hash" in changes or changes.get("disabled"):
            self.store.revoke_user_sessions(user_id)
        fields = sorted({"password" if key in {"password_hash", "password_changed_at"} else key for key in changes})
        self._audit("user.updated", actor=actor.subject, actor_kind=actor.kind, target_type="user", target_id=user_id, details={"username": user["username"], "fields": fields}, ctx=ctx)
        return self.user_payload(updated)

    def delete_user(self, actor: Principal, user_id: str, ctx: dict[str, Any]) -> None:
        user = self.store.get_user(user_id)
        if user is None:
            raise NotFound("user not found")
        if user_id == actor.user_id:
            raise Conflict("you cannot delete your own account")
        if user["role"] == "admin" and not user["disabled"] and self.store.count_admins(exclude_id=user_id) == 0:
            raise Conflict("cannot delete the last admin")
        self.store.delete_user(user_id)
        self._audit("user.deleted", actor=actor.subject, actor_kind=actor.kind, target_type="user", target_id=user_id, details={"username": user["username"], "role": user["role"]}, ctx=ctx)

    # ── OIDC ──────────────────────────────────────────────────────────────────

    def oidc_redirect_uri(self, request: Request) -> str:
        if self.oidc_config.redirect_uri:
            return self.oidc_config.redirect_uri
        scheme = "https" if is_https(request) else request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{scheme}://{host.split(',')[0].strip()}/api/auth/oidc/callback"

    def oidc_begin(self, request: Request) -> str:
        if self.oidc is None:
            raise Invalid("single sign-on is not configured (security.auth.oidc)")
        redirect_uri = self.oidc_redirect_uri(request)
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        self.store.save_oidc_state(state, nonce, verifier, redirect_uri, ttl=timedelta(minutes=STATE_TTL_MINUTES))
        return self.oidc.authorization_url(redirect_uri=redirect_uri, state=state, nonce=nonce, code_challenge=challenge)

    def oidc_complete(self, code: str | None, state: str | None, ctx: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if self.oidc is None:
            raise Invalid("single sign-on is not configured (security.auth.oidc)")
        row = self.store.pop_oidc_state(state) if state else None
        if row is None or not code:
            self._audit("auth.oidc_login", actor="-", actor_kind="anonymous", outcome="failure", details={"reason": "bad_state"}, ctx=ctx)
            raise Invalid("the sign-in attempt expired or is invalid; start again")
        try:
            tokens = self.oidc.exchange_code(code=code, code_verifier=row["code_verifier"], redirect_uri=row["redirect_uri"])
            claims = self.oidc.verify_id_token(str(tokens["id_token"]), nonce=row["nonce"])
            needs_groups = bool(self.oidc_config.admin_groups) and self.oidc_config.groups_claim not in claims
            if not claims.get("email") or needs_groups:
                claims = {**self.oidc.userinfo(str(tokens.get("access_token") or "")), **claims}
            identity = self.oidc.identity_from_claims(claims)
            user = self._upsert_oidc_user(identity, ctx)
            if user["disabled"]:
                raise Forbidden("this account is disabled")
        except PlatformError as exc:
            self._audit("auth.oidc_login", actor="-", actor_kind="anonymous", outcome="failure", details={"reason": exc.__class__.__name__, "message": str(exc)[:200]}, ctx=ctx)
            raise
        token = self._create_session(user, ctx, auth_method="oidc")
        user = self.store.update_user(user["id"], last_login_at=now_iso()) or user
        self._audit("auth.oidc_login", actor=user["username"], target_type="user", target_id=user["id"], details={"role": user["role"], "issuer": self.oidc_config.issuer}, ctx=ctx)
        return self.user_payload(user), token

    def _upsert_oidc_user(self, identity: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        issuer = self.oidc_config.issuer
        user = self.store.get_user_by_oidc(issuer, identity["subject"])
        if user is None:
            existing = self.store.get_user_by_username(identity["username"])
            if existing is not None:
                if existing.get("oidc_subject") and existing["oidc_subject"] != identity["subject"]:
                    raise Conflict("this username is linked to a different identity")
                if not identity["email_verified"]:
                    raise Conflict("a local account with this username exists and the identity provider did not assert a verified email; sign in with the password or ask an admin to remove the local account")
                linked = self.store.update_user(existing["id"], oidc_issuer=issuer, oidc_subject=identity["subject"], email=identity["email"])
                self._audit("user.updated", actor=identity["username"], actor_kind="system", target_type="user", target_id=existing["id"], details={"fields": ["oidc_link"], "issuer": issuer}, ctx=ctx)
                return linked or existing
            created = self.store.create_user(
                username=identity["username"], name=identity["name"], role=identity["role"], password_hash=None, auth_kind="oidc",
                email=identity["email"], oidc_issuer=issuer, oidc_subject=identity["subject"],
            )
            self._audit("user.created", actor=identity["username"], actor_kind="system", target_type="user", target_id=created["id"], details={"username": identity["username"], "role": identity["role"], "auth_kind": "oidc"}, ctx=ctx)
            return created
        changes: dict[str, Any] = {}
        if user["auth_kind"] == "oidc" and user["role"] != identity["role"]:
            if user["role"] == "admin" and not user["disabled"] and self.store.count_admins(exclude_id=user["id"]) == 0:
                logger.warning("auth: not demoting {} via OIDC groups: last remaining admin", user["username"])
            else:
                changes["role"] = identity["role"]
        if identity["name"] and user["name"] != identity["name"]:
            changes["name"] = identity["name"]
        if identity["email"] and user.get("email") != identity["email"]:
            changes["email"] = identity["email"]
        if changes:
            user = self.store.update_user(user["id"], **changes) or user
            self._audit("user.updated", actor=user["username"], actor_kind="system", target_type="user", target_id=user["id"], details={"fields": sorted(changes), "source": "oidc"}, ctx=ctx)
        return user

    # ── key rotation and housekeeping ─────────────────────────────────────────

    def rotate_secrets(self) -> int:
        """Re-encrypt stored TOTP secrets with the primary key; encrypt plaintext ones. Returns rows touched."""
        box = self.platform.secrets
        box.require()
        rotated = 0
        for row in self.store.mfa_secret_rows(encrypted=True):
            changes = {key: box.rotate(row[key]) for key in ("mfa_secret", "mfa_pending_secret") if row.get(key)}
            self.store.update_user(row["id"], **changes)
            rotated += 1
        for row in self.store.mfa_secret_rows(encrypted=False):
            changes = {key: box.encrypt_json(row[key]) for key in ("mfa_secret", "mfa_pending_secret") if row.get(key)}
            self.store.update_user(row["id"], mfa_secret_encrypted=1, **changes)
            rotated += 1
        return rotated

    def housekeeping(self) -> dict[str, int]:
        return {"sessions_purged": self.store.purge_sessions(), "attempts_purged": self.store.purge_attempts(timedelta(days=7))}
