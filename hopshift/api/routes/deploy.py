"""Deployments: terraform plan / apply / destroy for a run, variables and state.

Every mutation goes through `hopshift.services.deploy.DeployService`, which enforces the gates and writes
the audit trail; routes only translate HTTP into service calls (errors are mapped in api/app.py).
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hopshift.api.deps import Principal, audit_context, get_platform, get_runtime, require_role
from hopshift.pipeline.runtime import MigrationRuntime
from hopshift.services.platform import Platform

router = APIRouter(tags=["deployments"])


class CreateDeploymentBody(BaseModel):
    action: str  # plan | apply | destroy (validated by the service -> 400)
    connection_id: str | None = None
    plan_id: str | None = None
    confirmation: str | None = None


class VariablesBody(BaseModel):
    values: dict[str, Any]


def get_deploy_service(
    platform: Platform = Depends(get_platform), runtime: MigrationRuntime = Depends(get_runtime)
) -> Any:
    service = platform.deployments
    if service is None:
        raise HTTPException(status_code=503, detail="deployments are not available on this platform")
    service.bind_runtime(runtime)  # the service resolves run folders through the app's runtime
    return service


# ── deployments ──────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/deployments")
def list_deployments(run_id: str, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> list[dict[str, Any]]:
    return service.list(run_id)


@router.post("/runs/{run_id}/deployments", status_code=202)
def create_deployment(
    run_id: str,
    body: CreateDeploymentBody,
    request: Request,
    service: Any = Depends(get_deploy_service),
    principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    return service.create(
        run_id, action=body.action, connection_id=body.connection_id, plan_id=body.plan_id,
        confirmation=body.confirmation, actor=principal, context=audit_context(request),
    )


@router.get("/runs/{run_id}/deployments/{deployment_id}")
def get_deployment(run_id: str, deployment_id: str, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return service.get(run_id, deployment_id)


@router.get("/runs/{run_id}/deployments/{deployment_id}/log")
def deployment_log(run_id: str, deployment_id: str, since: int = 0, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return service.log(run_id, deployment_id, since=since)


@router.get("/runs/{run_id}/deployments/{deployment_id}/log/stream")
def stream_deployment_log(
    run_id: str, deployment_id: str, since: int = 0, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))
) -> StreamingResponse:
    service.get(run_id, deployment_id)  # 404 early

    def generate() -> Iterator[str]:
        cursor = since
        idle_ticks = 0
        while True:
            chunk = service.log(run_id, deployment_id, since=cursor)
            for offset, line in enumerate(chunk["lines"]):
                yield f"data: {json.dumps({'index': cursor + offset, 'line': line}, ensure_ascii=True)}\n\n"
            cursor = chunk["next"]
            if chunk["done"] and not chunk["lines"]:
                record = service.get(run_id, deployment_id)
                yield f"event: done\ndata: {json.dumps({'status': record['status'], 'exit_code': record['exit_code']})}\n\n"
                return
            idle_ticks = idle_ticks + 1 if not chunk["lines"] else 0
            if idle_ticks % 8 == 7:  # every ~4 s of silence
                yield ": keep-alive\n\n"
            time.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/runs/{run_id}/deployments/{deployment_id}/plan")
def deployment_plan(run_id: str, deployment_id: str, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return service.plan_json(run_id, deployment_id)


@router.post("/runs/{run_id}/deployments/{deployment_id}/cancel", status_code=202)
def cancel_deployment(
    run_id: str, deployment_id: str, request: Request, service: Any = Depends(get_deploy_service), principal: Principal = Depends(require_role("operator"))
) -> dict[str, Any]:
    return service.cancel(run_id, deployment_id, actor=principal, context=audit_context(request))


# ── variables and state ──────────────────────────────────────────────────────


@router.get("/runs/{run_id}/deploy/variables")
def get_variables(run_id: str, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> list[dict[str, Any]]:
    return service.variables(run_id)


@router.put("/runs/{run_id}/deploy/variables")
def put_variables(
    run_id: str, body: VariablesBody, request: Request, service: Any = Depends(get_deploy_service), principal: Principal = Depends(require_role("operator"))
) -> list[dict[str, Any]]:
    return service.set_variables(run_id, body.values, actor=principal, context=audit_context(request))


@router.get("/runs/{run_id}/deploy/state")
def get_state(run_id: str, service: Any = Depends(get_deploy_service), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return service.state_summary(run_id)
