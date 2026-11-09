"""Authentication endpoints: setup, login/logout, profile, password, MFA, OIDC, API tokens."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from api.deps import (
    ANONYMOUS_ADMIN,
    Principal,
    audit_context,
    current_principal,
    get_platform,
)
from vma.platform import Platform
from vma.security.service import AccountLocked, AuthService, LoginFailed, MfaRequired

router = APIRouter(tags=["auth"])

LOGIN_FAILED_DETAIL = "invalid username or password"
_ERROR_CODE_RE = re.compile(r"[^a-zA-Z0-9_.-]")


def _service(platform: Platform) -> AuthService:
    if platform.auth is None:
        raise HTTPException(status_code=400, detail="authentication is disabled (security.auth.mode: disabled)")
    return platform.auth


def _anonymous_payload() -> dict[str, Any]:
    return {
        "id": None, "username": ANONYMOUS_ADMIN.subject, "name": ANONYMOUS_ADMIN.name, "role": ANONYMOUS_ADMIN.role,
        "auth_kind": "anonymous", "disabled": False, "mfa_enabled": False, "mfa_enrollment_required": False, "email": None,
        "created_at": None, "updated_at": None, "last_login_at": None, "principal": ANONYMOUS_ADMIN.to_dict(),
    }


class SetupBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(default="", max_length=120)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=64)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class MfaConfirmBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class MfaDisableBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=64)


class TokenBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role: str | None = None
    expires_days: int | None = Field(default=None, ge=1, le=3650)


# ── status, setup, login ──────────────────────────────────────────────────────


@router.get("/auth/status")
def status(request: Request, platform: Platform = Depends(get_platform)) -> dict[str, Any]:
    """Public. Tells the UI whether to show setup, login or the app."""
    if platform.auth is None:
        return {"setup_required": False, "auth_mode": "disabled", "oidc_enabled": False, "mfa_policy": "optional", "user": _anonymous_payload()}
    return platform.auth.status(request)


@router.post("/auth/setup", status_code=201)
def setup(body: SetupBody, request: Request, response: Response, platform: Platform = Depends(get_platform)) -> dict[str, Any]:
    """Create the first admin (only while no users exist) and sign them in."""
    service = _service(platform)
    user, token = service.setup(body.username, body.password, body.name, audit_context(request))
    service.set_session_cookie(response, request, token)
    return user


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response, platform: Platform = Depends(get_platform)) -> Any:
    service = _service(platform)
    try:
        user, token = service.login(body.username, body.password, body.totp_code, audit_context(request))
    except MfaRequired:
        return JSONResponse({"detail": "mfa_required", "mfa_required": True}, status_code=401)
    except AccountLocked as exc:
        return JSONResponse(
            {"detail": "too many failed attempts; try again later"}, status_code=423, headers={"Retry-After": str(exc.retry_after)}
        )
    except LoginFailed:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED_DETAIL) from None
    service.set_session_cookie(response, request, token)
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, platform: Platform = Depends(get_platform)) -> Response:
    """Always succeeds and clears the cookie, also when the session already expired."""
    response = Response(status_code=204)
    if platform.auth is None:
        return response
    try:
        principal = platform.auth.authenticate(request)
    except HTTPException:
        principal = None
    platform.auth.logout(request, principal, audit_context(request))
    platform.auth.clear_session_cookie(response, request)
    return response


# ── profile ───────────────────────────────────────────────────────────────────


@router.get("/auth/me")
def me(platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if platform.auth is None:
        return _anonymous_payload()
    return platform.auth.me(principal)


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)
) -> Response:
    _service(platform).change_password(principal, request, body.current_password, body.new_password, audit_context(request))
    return Response(status_code=204)


# ── MFA ───────────────────────────────────────────────────────────────────────


@router.post("/auth/mfa/enroll")
def mfa_enroll(request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return _service(platform).mfa_enroll(principal, audit_context(request))


@router.post("/auth/mfa/confirm")
def mfa_confirm(
    body: MfaConfirmBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    return _service(platform).mfa_confirm(principal, body.code, audit_context(request))


@router.post("/auth/mfa/disable", status_code=204)
def mfa_disable(
    body: MfaDisableBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)
) -> Response:
    _service(platform).mfa_disable(principal, body.password, body.code, audit_context(request))
    return Response(status_code=204)


# ── OIDC ──────────────────────────────────────────────────────────────────────


@router.get("/auth/oidc/login")
def oidc_login(request: Request, platform: Platform = Depends(get_platform)) -> RedirectResponse:
    return RedirectResponse(_service(platform).oidc_begin(request), status_code=302)


@router.get("/auth/oidc/callback")
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    platform: Platform = Depends(get_platform),
) -> RedirectResponse:
    service = _service(platform)
    if error:
        raise HTTPException(status_code=400, detail=f"identity provider returned an error: {_ERROR_CODE_RE.sub('', error)[:64]}")
    _user, token = service.oidc_complete(code, state, audit_context(request))
    response = RedirectResponse("/#/", status_code=302)
    service.set_session_cookie(response, request, token)
    return response


# ── API tokens ────────────────────────────────────────────────────────────────


@router.get("/auth/tokens")
def list_tokens(
    include_all: bool = Query(default=False, alias="all", description="Admins: list every user's tokens."),
    platform: Platform = Depends(get_platform),
    principal: Principal = Depends(current_principal),
) -> list[dict[str, Any]]:
    return _service(platform).list_tokens(principal, include_all=include_all)


@router.post("/auth/tokens", status_code=201)
def create_token(
    body: TokenBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """The token value is returned once and never stored in clear."""
    return _service(platform).create_token(principal, body.name, body.role, body.expires_days, audit_context(request))


@router.delete("/auth/tokens/{token_id}", status_code=204)
def delete_token(
    token_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(current_principal)
) -> Response:
    _service(platform).delete_token(principal, token_id, audit_context(request))
    return Response(status_code=204)
