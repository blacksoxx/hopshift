"""FastAPI dependencies: platform access, the authenticated principal and role checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request

from hopshift.pipeline.runtime import MigrationRuntime
from hopshift.services.platform import Platform

ROLE_ORDER: dict[str, int] = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass
class Principal:
    subject: str
    kind: str  # user | token | anonymous | system
    role: str
    user_id: str | None = None
    name: str | None = None
    mfa: bool = False

    def allows(self, minimum_role: str) -> bool:
        return ROLE_ORDER.get(self.role, -1) >= ROLE_ORDER.get(minimum_role, 0)

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "kind": self.kind, "role": self.role, "user_id": self.user_id, "name": self.name, "mfa": self.mfa}


ANONYMOUS_ADMIN = Principal(subject="anonymous", kind="anonymous", role="admin", name="Anonymous (auth disabled)")


def get_platform(request: Request) -> Platform:
    return request.app.state.platform


def get_runtime(request: Request) -> MigrationRuntime:
    return request.app.state.runtime


def audit_context(request: Request) -> dict[str, str | None]:
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return {"ip": ip, "user_agent": request.headers.get("user-agent")}


def current_principal(request: Request) -> Principal:
    """The caller. With authentication disabled every caller is an anonymous admin."""
    platform: Platform = request.app.state.platform
    if platform.auth is None or platform.auth_mode == "disabled":
        return ANONYMOUS_ADMIN
    principal = platform.auth.authenticate(request)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def require_role(minimum_role: str) -> Callable[..., Principal]:
    if minimum_role not in ROLE_ORDER:
        raise ValueError(f"unknown role {minimum_role}")

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.allows(minimum_role):
            raise HTTPException(status_code=403, detail=f"{minimum_role} role required")
        return principal

    return dependency
