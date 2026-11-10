"""Password hashing (argon2id) and the password policy.

Verification always runs a real argon2 computation, also for unknown users (against a dummy
hash), so the response time does not reveal whether a username exists.
"""
from __future__ import annotations

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from hopshift.services.errors import Invalid

MIN_LENGTH = 12
MAX_LENGTH = 256

# argon2id with the library defaults (t=3, m=64 MiB, p=4), OWASP's recommended configuration.
_hasher = PasswordHasher(type=Type.ID)
# A hash of a random throwaway password; used to burn the same time when the user is unknown.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification: an absent hash is verified against the dummy hash and fails."""
    target = password_hash or DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return bool(ok) and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:  # pragma: no cover - malformed stored hash
        return True


def validate_password(password: str, username: str | None = None) -> None:
    """Policy: at least 12 characters, at most 256, not containing the username."""
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise Invalid(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise Invalid(f"password must be at most {MAX_LENGTH} characters")
    if not password.strip():
        raise Invalid("password must not be blank")
    if username:
        needle = username.strip().lower()
        local_part = needle.split("@", 1)[0]
        for part in {needle, local_part}:
            if len(part) >= 3 and part in password.lower():
                raise Invalid("password must not contain the username")
