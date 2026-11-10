from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from hopshift.api.deps import Principal, audit_context, get_platform, get_runtime, require_role
from hopshift.pipeline.runtime import MigrationRuntime
from hopshift.services.platform import Platform
from hopshift.services.settings import SettingsError, SettingsStore

router = APIRouter(tags=["settings"])


class SettingsBody(BaseModel):
    values: dict[str, Any]


@router.get("/settings")
def get_settings(platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    return {
        "effective": platform.settings.effective_values(platform.config),
        "overrides": platform.settings.overrides(),
        "schema": SettingsStore.schema(),
    }


@router.put("/settings")
def put_settings(
    body: SettingsBody,
    request: Request,
    platform: Platform = Depends(get_platform),
    runtime: MigrationRuntime = Depends(get_runtime),
    principal: Principal = Depends(require_role("admin")),
) -> dict[str, Any]:
    try:
        overrides = platform.settings.update(body.values, actor=principal.subject)
    except SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.base_config = platform.effective_config()
    platform.audit.record(
        "settings.updated", actor=principal.subject, actor_kind=principal.kind, target_type="settings",
        details={"keys": sorted(body.values)}, **audit_context(request),
    )
    return {"effective": platform.settings.effective_values(platform.config), "overrides": overrides, "schema": SettingsStore.schema()}


@router.get("/settings/posture")
def posture(request: Request, platform: Platform = Depends(get_platform), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    """Live security posture of this deployment (evidence for SOC 2 / HIPAA / CIS reviews)."""
    checks = platform.extras.get("posture_checks")
    if callable(checks):
        return {"checks": checks(platform, request)}
    return {"checks": _basic_posture(platform, request)}


def _basic_posture(platform: Platform, request: Request) -> list[dict[str, Any]]:
    config = platform.effective_config()
    security = config.get("security") if isinstance(config.get("security"), dict) else {}
    retention = security.get("retention") if isinstance(security.get("retention"), dict) else {}
    verification = platform.audit.verify()
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"
    return [
        {"id": "auth.enforced", "title": "Authentication enforced", "status": "pass" if platform.auth_mode != "disabled" else "fail",
         "detail": f"auth mode is {platform.auth_mode}", "frameworks": ["SOC2 CC6.1", "HIPAA 164.312(d)", "CIS 6.3"]},
        {"id": "secrets.key", "title": "Secrets encryption key configured", "status": "pass" if platform.secrets.available else "fail",
         "detail": f"{platform.secrets.env_var} {'set' if platform.secrets.available else 'missing'}", "frameworks": ["SOC2 CC6.1", "HIPAA 164.312(a)(2)(iv)"]},
        {"id": "audit.chain", "title": "Audit log integrity", "status": "pass" if verification.ok else "fail",
         "detail": f"{verification.entries} entries, {verification.message}", "frameworks": ["SOC2 CC7.2", "HIPAA 164.312(b)", "CIS 8.2"]},
        {"id": "transport.tls", "title": "TLS in use", "status": "pass" if https else "warn",
         "detail": "request arrived over HTTPS" if https else "request arrived over plain HTTP; terminate TLS in front of the API",
         "frameworks": ["SOC2 CC6.7", "HIPAA 164.312(e)(1)", "CIS 3.10"]},
        {"id": "retention.runs", "title": "Run retention configured", "status": "pass" if int(retention.get("runs_days") or 0) > 0 else "warn",
         "detail": f"runs_days={retention.get('runs_days') or 0}", "frameworks": ["SOC2 CC6.5", "HIPAA 164.310(d)(2)(i)"]},
    ]
