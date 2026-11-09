"""Security workstream: users, sessions, API tokens, RBAC, MFA, OIDC, lockout, retention, posture.

`vma.platform.Platform.from_config` imports this package before running migrations (so the
tables in `store.py` register) and then calls `build_auth_service(platform)`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from vma.security import store as _store  # noqa: F401  (registers the security_* migrations)
from vma.security.posture import posture_checks

if TYPE_CHECKING:  # pragma: no cover
    from vma.security.service import AuthService

AUTH_MODES = ("required", "disabled")


def auth_mode_of(config: dict[str, Any]) -> str:
    """`security.auth.mode`; a missing section means `required` (secure default)."""
    security = config.get("security") if isinstance(config.get("security"), dict) else {}
    auth = security.get("auth") if isinstance(security.get("auth"), dict) else {}
    mode = str(auth.get("mode") or "required").strip().lower()
    if mode not in AUTH_MODES:
        logger.warning("security: unknown security.auth.mode {!r}; treating it as 'required'", mode)
        return "required"
    return mode


def build_auth_service(platform: Any) -> "AuthService | None":
    platform.extras["posture_checks"] = posture_checks
    if auth_mode_of(platform.config) == "disabled":
        logger.warning("security: authentication is DISABLED (security.auth.mode: disabled); every caller is an anonymous admin. Local development only.")
        return None
    from vma.security.service import AuthService

    return AuthService(platform)


__all__ = ["build_auth_service", "auth_mode_of", "posture_checks"]
