from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from hopshift.api.deps import Principal, get_platform, get_runtime, require_role
from hopshift.api.serialization import jsonable
from hopshift.pipeline.graph import NODE_ORDER
from hopshift.pipeline.runtime import GENERATION_MODES, PAUSE_POINTS, MigrationRuntime
from hopshift.services import __version__
from hopshift.services.platform import Platform
from hopshift.sources import registry as sources
from hopshift.targets import registry as targets

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(runtime: MigrationRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return {"ok": True, "runs_dir": str(runtime.store.root), "version": __version__}


@router.get("/meta")
def meta(runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform)) -> dict[str, Any]:
    return {
        "version": __version__,
        "clouds": targets.names(),
        "targets": [spec.to_dict() for spec in targets.all_specs()],
        "sources": [spec.to_dict() for spec in sources.all_specs()],
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
