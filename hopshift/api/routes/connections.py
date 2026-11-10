"""Cloud connections: catalog, CRUD, verification and device-code sign-in.

Responses always go through `ConnectionService.to_public`, which never includes secret values
(only `has_secret` and the names of the stored secret fields).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from hopshift.api.deps import Principal, audit_context, get_platform, require_role
from hopshift.services.connections import ConnectionService
from hopshift.services.platform import Platform

router = APIRouter(tags=["connections"])


class CreateConnectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str
    auth_method: str
    config: dict[str, Any] = Field(default_factory=dict)
    secret: dict[str, Any] = Field(default_factory=dict)


class UpdateConnectionBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: dict[str, Any] | None = None
    secret: dict[str, Any] | None = None


class DevicePollBody(BaseModel):
    flow_id: str = Field(min_length=1, max_length=64)


def _service(platform: Platform) -> ConnectionService:
    if platform.connections is None:
        raise HTTPException(status_code=503, detail="the connections service is not available")
    return platform.connections


# ── catalog and reads (viewer) ────────────────────────────────────────────────


@router.get("/connections/methods")
def connection_methods(platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return _service(platform).catalog()


@router.get("/connections")
def list_connections(
    provider: str | None = None, platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("viewer")),
) -> list[dict[str, Any]]:
    service = _service(platform)
    return [service.to_public(item) for item in service.list() if not provider or item.provider == provider]


@router.get("/connections/{connection_id}")
def get_connection(connection_id: str, platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    service = _service(platform)
    return service.to_public(service.get(connection_id))


# ── management (admin) ────────────────────────────────────────────────────────


@router.post("/connections", status_code=201)
def create_connection(
    body: CreateConnectionBody, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    service = _service(platform)
    connection = service.create(
        name=body.name, provider=body.provider, auth_method=body.auth_method, config=body.config, secret=body.secret,
        actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request),
    )
    return service.to_public(connection)


@router.patch("/connections/{connection_id}")
def update_connection(
    connection_id: str, body: UpdateConnectionBody, request: Request,
    platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    service = _service(platform)
    connection = service.update(
        connection_id, name=body.name, config=body.config, secret=body.secret,
        actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request),
    )
    return service.to_public(connection)


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(
    connection_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("admin")),
) -> Response:
    _service(platform).delete(connection_id, actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request))
    return Response(status_code=204)


# ── verification and device flows (operator) ──────────────────────────────────


@router.post("/connections/{connection_id}/test")
def test_connection(
    connection_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    return _service(platform).test(connection_id, actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request))


@router.post("/connections/{connection_id}/device/start")
def device_start(
    connection_id: str, request: Request, platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    return _service(platform).device_start(connection_id, actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request))


@router.post("/connections/{connection_id}/device/poll")
def device_poll(
    connection_id: str, body: DevicePollBody, request: Request,
    platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    return _service(platform).device_poll(
        connection_id, body.flow_id, actor=principal.subject, actor_kind=principal.kind, audit_context=audit_context(request),
    )
