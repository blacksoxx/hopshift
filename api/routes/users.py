"""User administration (admin role)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.deps import Principal, audit_context, get_platform, require_role
from vma.platform import Platform
from vma.security.service import AuthService

router = APIRouter(tags=["users"])


def _service(platform: Platform) -> AuthService:
    if platform.auth is None:
        raise HTTPException(status_code=400, detail="authentication is disabled (security.auth.mode: disabled)")
    return platform.auth


class CreateUserBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(default="", max_length=120)
    role: str = Field(default="viewer", max_length=16)


class UpdateUserBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=16)
    disabled: bool | None = None
    password: str | None = Field(default=None, min_length=1, max_length=256)


@router.get("/users")
def list_users(platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("admin"))) -> list[dict[str, Any]]:
    return _service(platform).list_users()


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin"))
) -> dict[str, Any]:
    return _service(platform).create_user(principal, body.username, body.password, body.name, body.role, audit_context(request))


@router.get("/users/{user_id}")
def get_user(user_id: str, platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    return _service(platform).get_user(user_id)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UpdateUserBody,
    request: Request,
    platform: Platform = Depends(get_platform),
    principal: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    return _service(platform).update_user(
        principal, user_id, name=body.name, role=body.role, disabled=body.disabled, password=body.password, ctx=audit_context(request)
    )


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin"))
) -> Response:
    _service(platform).delete_user(principal, user_id, audit_context(request))
    return Response(status_code=204)


@router.post("/users/{user_id}/mfa/reset")
def reset_mfa(
    user_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin"))
) -> dict[str, Any]:
    """Clear the user's second factor (lost device); their sessions are revoked and they re-enrol."""
    return _service(platform).mfa_reset(principal, user_id, audit_context(request))
