"""SQLite persistence for the security service: users, sessions, API tokens, MFA recovery
codes, OIDC login states and login attempts.

Only hashes of credentials are stored: argon2id for passwords, sha256 for session and API
tokens (random 256-bit values, so a fast hash is appropriate) and for recovery codes. TOTP
secrets are stored encrypted with the platform secret box when a key is configured; the
`mfa_secret_encrypted` flag records which form a row holds so the posture check can report
unencrypted secrets and `rotate_secrets()` can re-encrypt them.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from vma.db import Database, register_migration

register_migration(
    "security_001_users",
    """
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY,
      username TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL DEFAULT '',
      role TEXT NOT NULL,
      auth_kind TEXT NOT NULL DEFAULT 'password',
      password_hash TEXT,
      disabled INTEGER NOT NULL DEFAULT 0,
      mfa_enabled INTEGER NOT NULL DEFAULT 0,
      mfa_secret TEXT,
      mfa_pending_secret TEXT,
      mfa_secret_encrypted INTEGER NOT NULL DEFAULT 0,
      mfa_last_step INTEGER,
      email TEXT,
      oidc_issuer TEXT,
      oidc_subject TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      last_login_at TEXT,
      password_changed_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS users_oidc ON users(oidc_issuer, oidc_subject) WHERE oidc_subject IS NOT NULL;
    """,
)

register_migration(
    "security_002_sessions",
    """
    CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      ip TEXT,
      user_agent TEXT,
      auth_method TEXT NOT NULL DEFAULT 'password',
      revoked_at TEXT
    );
    CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
    """,
)

register_migration(
    "security_003_api_tokens",
    """
    CREATE TABLE IF NOT EXISTS api_tokens (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      token_hash TEXT NOT NULL UNIQUE,
      prefix TEXT NOT NULL,
      role TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT,
      last_used_at TEXT,
      revoked_at TEXT
    );
    CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
    """,
)

register_migration(
    "security_004_mfa_recovery_codes",
    """
    CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      code_hash TEXT NOT NULL,
      created_at TEXT NOT NULL,
      used_at TEXT
    );
    CREATE INDEX IF NOT EXISTS mfa_recovery_codes_user ON mfa_recovery_codes(user_id);
    """,
)

register_migration(
    "security_005_oidc_states",
    """
    CREATE TABLE IF NOT EXISTS oidc_states (
      state TEXT PRIMARY KEY,
      nonce TEXT NOT NULL,
      code_verifier TEXT NOT NULL,
      redirect_uri TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );
    """,
)

register_migration(
    "security_006_login_attempts",
    """
    CREATE TABLE IF NOT EXISTS login_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL,
      ip TEXT,
      success INTEGER NOT NULL,
      ts TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS login_attempts_user_ts ON login_attempts(username, ts);
    """,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """ISO 8601 UTC with second precision, the format used across run records and this store."""
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(utc_now())


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_id() -> str:
    return secrets.token_hex(8)


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class SecurityStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── users ─────────────────────────────────────────────────────────────────

    def count_users(self) -> int:
        with self.db.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def count_admins(self, *, exclude_id: str | None = None) -> int:
        with self.db.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0 AND id != ?",
                    (exclude_id or "",),
                ).fetchone()[0]
            )

    def count_users_without_mfa(self) -> int:
        with self.db.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE disabled = 0 AND auth_kind = 'password' AND mfa_enabled = 0"
                ).fetchone()[0]
            )

    def count_plaintext_mfa_secrets(self) -> int:
        with self.db.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE mfa_secret_encrypted = 0"
                    " AND (mfa_secret IS NOT NULL OR mfa_pending_secret IS NOT NULL)"
                ).fetchone()[0]
            )

    def list_users(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC, username ASC").fetchall()
        return [dict(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(conn.execute("SELECT * FROM users WHERE username = ?", (normalize_username(username),)).fetchone())

    def get_user_by_oidc(self, issuer: str, subject: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(
                conn.execute("SELECT * FROM users WHERE oidc_issuer = ? AND oidc_subject = ?", (issuer, subject)).fetchone()
            )

    def create_user(
        self,
        *,
        username: str,
        name: str,
        role: str,
        password_hash: str | None,
        auth_kind: str = "password",
        email: str | None = None,
        oidc_issuer: str | None = None,
        oidc_subject: str | None = None,
    ) -> dict[str, Any]:
        now = now_iso()
        user_id = new_id()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, name, role, auth_kind, password_hash, email, oidc_issuer, oidc_subject,"
                " created_at, updated_at, password_changed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    user_id, normalize_username(username), name, role, auth_kind, password_hash, email, oidc_issuer,
                    oidc_subject, now, now, now if password_hash else None,
                ),
            )
        user = self.get_user(user_id)
        assert user is not None
        return user

    def create_first_user(self, *, username: str, name: str, password_hash: str) -> dict[str, Any] | None:
        """Atomically create the first admin; returns None when a user already exists (lost race)."""
        now = now_iso()
        user_id = new_id()
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (id, username, name, role, auth_kind, password_hash, created_at, updated_at, password_changed_at)"
                " SELECT ?,?,?,'admin','password',?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM users)",
                (user_id, normalize_username(username), name, password_hash, now, now, now),
            )
            created = bool(cursor.rowcount)
        return self.get_user(user_id) if created else None

    def update_user(self, user_id: str, **fields: Any) -> dict[str, Any] | None:
        if not fields:
            return self.get_user(user_id)
        allowed = {
            "name", "role", "disabled", "password_hash", "mfa_enabled", "mfa_secret", "mfa_pending_secret",
            "mfa_secret_encrypted", "mfa_last_step", "email", "oidc_issuer", "oidc_subject", "last_login_at",
            "password_changed_at", "auth_kind",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update user fields {sorted(unknown)}")
        fields["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", [*fields.values(), user_id])
        return self.get_user(user_id)

    def delete_user(self, user_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            return bool(cursor.rowcount)

    # ── sessions ──────────────────────────────────────────────────────────────

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        *,
        lifetime: timedelta,
        ip: str | None,
        user_agent: str | None,
        auth_method: str = "password",
    ) -> dict[str, Any]:
        now = utc_now()
        session_id = new_id()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at, last_seen_at, ip, user_agent, auth_method)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (session_id, user_id, token_hash, iso(now), iso(now + lifetime), iso(now), ip, (user_agent or "")[:300] or None, auth_method),
            )
        session = self.get_session_by_hash(token_hash)
        assert session is not None
        return session

    def get_session_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone())

    def touch_session(self, session_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now_iso(), session_id))

    def revoke_session(self, session_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now_iso(), session_id))

    def revoke_user_sessions(self, user_id: str, *, keep_session_id: str | None = None) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id != ?",
                (now_iso(), user_id, keep_session_id or ""),
            )
            return int(cursor.rowcount or 0)

    def purge_sessions(self) -> int:
        """Remove revoked or expired sessions (housekeeping; revoked rows carry no value)."""
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE revoked_at IS NOT NULL OR expires_at < ?", (now_iso(),))
            return int(cursor.rowcount or 0)

    # ── API tokens ────────────────────────────────────────────────────────────

    def create_token(
        self, *, user_id: str, name: str, token_hash: str, prefix: str, role: str, expires_at: str | None
    ) -> dict[str, Any]:
        token_id = new_id()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO api_tokens (id, user_id, name, token_hash, prefix, role, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (token_id, user_id, name, token_hash, prefix, role, now_iso(), expires_at),
            )
        token = self.get_token(token_id)
        assert token is not None
        return token

    def get_token(self, token_id: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(conn.execute("SELECT * FROM api_tokens WHERE id = ?", (token_id,)).fetchone())

    def get_token_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self.db.connect() as conn:
            return _row(conn.execute("SELECT * FROM api_tokens WHERE token_hash = ?", (token_hash,)).fetchone())

    def list_tokens(self, user_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    "SELECT t.*, u.username AS username FROM api_tokens t JOIN users u ON u.id = t.user_id"
                    " WHERE t.revoked_at IS NULL ORDER BY t.created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT t.*, u.username AS username FROM api_tokens t JOIN users u ON u.id = t.user_id"
                    " WHERE t.user_id = ? AND t.revoked_at IS NULL ORDER BY t.created_at DESC",
                    (user_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def touch_token(self, token_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (now_iso(), token_id))

    def revoke_token(self, token_id: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (now_iso(), token_id))
            return bool(cursor.rowcount)

    # ── MFA recovery codes ────────────────────────────────────────────────────

    def replace_recovery_codes(self, user_id: str, code_hashes: list[str]) -> None:
        now = now_iso()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM mfa_recovery_codes WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO mfa_recovery_codes (user_id, code_hash, created_at) VALUES (?,?,?)",
                [(user_id, code_hash, now) for code_hash in code_hashes],
            )

    def unused_recovery_codes(self, user_id: str) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, code_hash FROM mfa_recovery_codes WHERE user_id = ? AND used_at IS NULL", (user_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def use_recovery_code(self, code_id: int) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute("UPDATE mfa_recovery_codes SET used_at = ? WHERE id = ? AND used_at IS NULL", (now_iso(), code_id))
            return bool(cursor.rowcount)

    def delete_recovery_codes(self, user_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM mfa_recovery_codes WHERE user_id = ?", (user_id,))

    # ── OIDC states ───────────────────────────────────────────────────────────

    def save_oidc_state(self, state: str, nonce: str, code_verifier: str, redirect_uri: str, ttl: timedelta) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute("DELETE FROM oidc_states WHERE expires_at < ?", (iso(now),))
            conn.execute(
                "INSERT INTO oidc_states (state, nonce, code_verifier, redirect_uri, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (state, nonce, code_verifier, redirect_uri, iso(now), iso(now + ttl)),
            )

    def pop_oidc_state(self, state: str) -> dict[str, Any] | None:
        """Single use: return and delete the row (expired rows are reported as missing)."""
        with self.db.connect() as conn:
            row = _row(conn.execute("SELECT * FROM oidc_states WHERE state = ?", (state,)).fetchone())
            if row is not None:
                conn.execute("DELETE FROM oidc_states WHERE state = ?", (state,))
        if row is None:
            return None
        expires = parse_iso(row["expires_at"])
        if expires is None or expires < utc_now():
            return None
        return row

    # ── login attempts (lockout) ──────────────────────────────────────────────

    def record_attempt(self, username: str, ip: str | None, success: bool) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO login_attempts (username, ip, success, ts) VALUES (?,?,?,?)",
                (normalize_username(username), ip, 1 if success else 0, now_iso()),
            )

    def recent_failures(self, username: str, window: timedelta) -> tuple[int, str | None]:
        """Failed attempts for the username within the window and the timestamp of the latest one."""
        since = iso(utc_now() - window)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n, MAX(ts) AS latest FROM login_attempts WHERE username = ? AND success = 0 AND ts >= ?",
                (normalize_username(username), since),
            ).fetchone()
        return int(row["n"]), row["latest"]

    def clear_attempts(self, username: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM login_attempts WHERE username = ?", (normalize_username(username),))

    def purge_attempts(self, older_than: timedelta) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM login_attempts WHERE ts < ?", (iso(utc_now() - older_than),))
            return int(cursor.rowcount or 0)

    # ── secrets rotation ──────────────────────────────────────────────────────

    def mfa_secret_rows(self, *, encrypted: bool) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, mfa_secret, mfa_pending_secret FROM users WHERE mfa_secret_encrypted = ?"
                " AND (mfa_secret IS NOT NULL OR mfa_pending_secret IS NOT NULL)",
                (1 if encrypted else 0,),
            ).fetchall()
        return [dict(row) for row in rows]
