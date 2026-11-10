"""Encryption at rest for stored secrets (cloud credentials, MFA secrets, OIDC client secrets).

The key comes from the environment (`HOPSHIFT_SECRET_KEY` by default) and never from a file in the
repository. The variable may hold several comma-separated Fernet keys: the first encrypts, all
of them decrypt, which is how rotation works (`hopshift secrets rotate`). Without a key the box is
unavailable and services must refuse to store secrets with a clear message.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

DEFAULT_KEY_ENV = "HOPSHIFT_SECRET_KEY"
_REDACTED = "***"


class SecretsUnavailable(RuntimeError):
    """No encryption key is configured."""


class SecretBox:
    def __init__(self, keys: list[str] | None, env_var: str = DEFAULT_KEY_ENV) -> None:
        self.env_var = env_var
        cleaned = [key.strip() for key in (keys or []) if key and key.strip()]
        try:
            self._fernets = [Fernet(key.encode("ascii")) for key in cleaned]
        except (ValueError, UnicodeEncodeError) as exc:
            raise SecretsUnavailable(
                f"{env_var} is not a valid Fernet key (expected 32 url-safe base64 bytes; "
                "generate one with `hopshift secrets generate-key`)"
            ) from exc
        self._multi = MultiFernet(self._fernets) if self._fernets else None
        self.fingerprint = hashlib.sha256(cleaned[0].encode("ascii")).hexdigest()[:12] if cleaned else None

    @classmethod
    def from_env(cls, env_var: str = DEFAULT_KEY_ENV) -> "SecretBox":
        raw = os.environ.get(env_var, "")
        return cls(raw.split(",") if raw else None, env_var=env_var)

    @property
    def available(self) -> bool:
        return self._multi is not None

    def require(self) -> MultiFernet:
        if self._multi is None:
            raise SecretsUnavailable(
                f"no encryption key configured: set {self.env_var} (generate one with `hopshift secrets generate-key`)"
            )
        return self._multi

    def encrypt_json(self, data: Any) -> str:
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")
        return self.require().encrypt(payload).decode("ascii")

    def decrypt_json(self, token: str) -> Any:
        try:
            payload = self.require().decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            raise SecretsUnavailable("stored secret cannot be decrypted with the configured key(s)") from exc
        return json.loads(payload.decode("utf-8"))

    def rotate(self, token: str) -> str:
        """Re-encrypt a token with the primary key (decrypting with any configured key)."""
        return self.require().rotate(token.encode("ascii")).decode("ascii")

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode("ascii")


def mask_values(text: str, values: list[str]) -> str:
    """Replace every occurrence of the given secret values in `text` with a marker."""
    masked = text
    for value in sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True):
        masked = masked.replace(value, _REDACTED)
    return masked


_SECRET_KEY_PATTERN = re.compile(r"(secret|password|token|credential|private_key|client_secret|key_json)", re.IGNORECASE)


def redact_mapping(data: Any) -> Any:
    """Return a copy with values under secret-looking keys replaced, for logs and API responses."""
    if isinstance(data, dict):
        return {
            str(key): (_REDACTED if _SECRET_KEY_PATTERN.search(str(key)) and value not in (None, "") else redact_mapping(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact_mapping(item) for item in data]
    return data
