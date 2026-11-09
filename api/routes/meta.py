from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from agent.graph import NODE_ORDER
from agent.runtime import GENERATION_MODES, PAUSE_POINTS, MigrationRuntime
from api.deps import Principal, get_platform, get_runtime, require_role
from api.serialization import jsonable
from cim.schema import TargetProvider
from vma import __version__
from vma.platform import Platform

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(runtime: MigrationRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return {"ok": True, "runs_dir": str(runtime.store.root), "version": __version__}


@router.get("/meta")
def meta(runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform)) -> dict[str, Any]:
    return {
        "version": __version__,
        "clouds": [provider.value for provider in TargetProvider],
        "modes": list(GENERATION_MODES),
        "pause_points": PAUSE_POINTS,
        "nodes": list(NODE_ORDER),
        "default_pause_points": runtime.default_pause_points,
        "auth_mode": platform.auth_mode,
        "features": {
            "connections": platform.connections is not None,
            "deployments": platform.deployments is not None,
            "secrets": platform.secrets.available,
        },
    }


@router.get("/config")
def config(runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    return jsonable(runtime.base_config)
