from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hopshift.api.deps import Principal, get_runtime, require_role
from hopshift.api.serialization import jsonable
from hopshift.pipeline.runtime import MigrationRuntime, RunOptions, build_run_config, initial_state

router = APIRouter(tags=["assess"])


class AssessBody(BaseModel):
    discovery: dict[str, Any]
    cloud: str


@router.post("/assess")
def assess(body: AssessBody, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    """Synchronous readiness assessment; no cloud or LLM access, nothing written."""
    from hopshift.pipeline.graph import build_assess_graph

    options = RunOptions(cloud=body.cloud, environment="assess", owner="assess", dry_run=True)
    options.validate()
    cfg = build_run_config(runtime.base_config, options, runtime.store.root / "_assess")
    state = initial_state(body.discovery, cfg, body.cloud)
    final = build_assess_graph().invoke(state)
    return jsonable(final.get("assessment_result", {}))
