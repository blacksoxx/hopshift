from __future__ import annotations

import difflib
import io
import json
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from agent.graph import NODE_ORDER
from agent.runtime import TERMINAL_STATUSES, MigrationRuntime, RunError, RunOptions
from api.deps import Principal, audit_context, get_platform, get_runtime, require_role
from vma.platform import Platform

router = APIRouter(tags=["runs"])


class RunOptionsBody(BaseModel):
    cloud: str
    environment: str
    owner: str
    mode: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    skip_validation: bool = False
    skip_opa: bool = False
    no_mcp: bool = False
    dry_run: bool = False
    llm_review_notes: bool = True
    pause_points: list[str] | None = None

    def to_options(self) -> RunOptions:
        return RunOptions(**self.model_dump())


class CreateRunBody(BaseModel):
    discovery: dict[str, Any]
    options: RunOptionsBody
    input_filename: str = "discovery.json"
    start: bool = False
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    connection_id: str | None = None


class UpdateRunBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    connection_id: str | None = None
    clear_connection: bool = False


class PatchStateBody(BaseModel):
    values: dict[str, Any]


class RerunBody(BaseModel):
    node: str


def _executing(request: Request, run_id: str) -> bool:
    from api.app import is_executing

    return is_executing(request.app, run_id)


def _submit(request: Request, run_id: str, fn: Any, *args: Any) -> None:
    from api.app import submit_run

    submit_run(request.app, run_id, fn, *args)


def _audit(platform: Platform, request: Request, principal: Principal, action: str, run_id: str, **details: Any) -> None:
    platform.audit.record(
        action, actor=principal.subject, actor_kind=principal.kind, target_type="run", target_id=run_id,
        details=details, **audit_context(request),
    )


# ── listing and dashboard ─────────────────────────────────────────────────────


@router.get("/runs")
def list_runs(
    request: Request,
    status: str | None = None,
    cloud: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    runtime: MigrationRuntime = Depends(get_runtime),
    _: Principal = Depends(require_role("viewer")),
) -> list[dict[str, Any]]:
    records = runtime.list_runs()
    needle = (q or "").strip().lower()
    items: list[dict[str, Any]] = []
    for record in records:
        if status and record.status != status:
            continue
        if cloud and record.cloud != cloud:
            continue
        if tag and tag not in record.tags:
            continue
        if needle and needle not in " ".join([record.run_id, record.name or "", record.input_filename, *record.tags]).lower():
            continue
        payload = record.to_dict()
        payload["executing"] = _executing(request, record.run_id)
        items.append(payload)
    return items


@router.get("/dashboard")
def dashboard(runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    records = runtime.list_runs()
    by_status = Counter(record.status for record in records)
    by_cloud = Counter(record.cloud for record in records)
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
    series = {day: {"date": day, "succeeded": 0, "failed": 0, "other": 0} for day in days}
    for record in records:
        day = record.created_at[:10]
        bucket = series.get(day)
        if bucket is None:
            continue
        key = "succeeded" if record.status == "succeeded" else "failed" if record.status in {"failed", "error"} else "other"
        bucket[key] += 1
    finished = [record for record in records if record.status in TERMINAL_STATUSES]
    success_rate = round(100 * sum(1 for record in finished if record.status == "succeeded") / len(finished)) if finished else None
    recent = sorted(records, key=lambda record: record.updated_at, reverse=True)[:8]
    return {
        "total": len(records),
        "by_status": dict(by_status),
        "by_cloud": dict(by_cloud),
        "success_rate": success_rate,
        "series": list(series.values()),
        "recent": [record.to_dict() for record in recent],
        "attention": [record.to_dict() for record in records if record.status == "paused"][:8],
    }


# ── lifecycle ─────────────────────────────────────────────────────────────────


@router.post("/runs", status_code=201)
def create_run(
    body: CreateRunBody,
    request: Request,
    runtime: MigrationRuntime = Depends(get_runtime),
    platform: Platform = Depends(get_platform),
    principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    if body.connection_id and platform.connections is not None:
        platform.connections.get(body.connection_id)  # 404 if unknown
    record = runtime.create_run(
        body.discovery, body.options.to_options(), input_filename=body.input_filename,
        name=body.name, tags=body.tags, connection_id=body.connection_id, created_by=principal.subject,
    )
    _audit(platform, request, principal, "run.created", record.run_id, cloud=record.cloud, mode=record.mode, start=body.start)
    if body.start:
        _submit(request, record.run_id, runtime.start, record.run_id)
        record.status = "running"
    payload = record.to_dict()
    payload["executing"] = body.start
    return payload


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    payload = runtime.get_run(run_id).to_dict()
    payload["executing"] = _executing(request, run_id)
    return payload


@router.patch("/runs/{run_id}")
def update_run(
    run_id: str,
    body: UpdateRunBody,
    request: Request,
    runtime: MigrationRuntime = Depends(get_runtime),
    platform: Platform = Depends(get_platform),
    principal: Principal = Depends(require_role("operator")),
) -> dict[str, Any]:
    if body.connection_id and platform.connections is not None:
        platform.connections.get(body.connection_id)
    record = runtime.update_run(
        run_id, name=body.name, tags=body.tags,
        connection_id=None if body.clear_connection else body.connection_id, clear_connection=body.clear_connection,
    )
    _audit(platform, request, principal, "run.updated", run_id, fields=[k for k, v in body.model_dump().items() if v not in (None, False)])
    payload = record.to_dict()
    payload["executing"] = _executing(request, run_id)
    return payload


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(
    run_id: str,
    request: Request,
    runtime: MigrationRuntime = Depends(get_runtime),
    platform: Platform = Depends(get_platform),
    principal: Principal = Depends(require_role("operator")),
) -> Response:
    if _executing(request, run_id):
        raise HTTPException(status_code=409, detail=f"run {run_id} is executing; cancel it first")
    if platform.deployments is not None and platform.deployments.has_active(run_id):
        raise HTTPException(status_code=409, detail=f"run {run_id} has an active deployment")
    runtime.delete_run(run_id)
    request.app.state.futures.pop(run_id, None)
    _audit(platform, request, principal, "run.deleted", run_id)
    return Response(status_code=204)


@router.post("/runs/{run_id}/start", status_code=202)
def start_run(run_id: str, request: Request, runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator"))) -> dict[str, Any]:
    record = runtime.get_run(run_id)
    if record.status != "created":
        raise RunError(f"run {run_id} is {record.status}; only a created run can be started")
    _submit(request, run_id, runtime.start, run_id)
    _audit(platform, request, principal, "run.started", run_id)
    return {"run_id": run_id, "status": "running"}


@router.post("/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: str, request: Request, runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator"))) -> dict[str, Any]:
    record = runtime.get_run(run_id)
    if record.status != "paused":
        raise RunError(f"run {run_id} is {record.status}; only a paused run can be resumed")
    _submit(request, run_id, runtime.resume, run_id)
    _audit(platform, request, principal, "run.approved", run_id, pause_point=record.pause_point)
    return {"run_id": run_id, "status": "running", "resumed_from": record.pause_point}


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, request: Request, runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator"))) -> dict[str, Any]:
    record = runtime.cancel(run_id)
    _audit(platform, request, principal, "run.cancelled", run_id, status=record.status)
    return {"run_id": run_id, "status": record.status, "cancel_requested": record.cancel_requested}


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: str, body: RerunBody, request: Request, runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator"))) -> dict[str, Any]:
    record = runtime.get_run(run_id)
    if record.status in {"running", "created"}:
        raise RunError(f"run {run_id} is {record.status}; it cannot be re-run yet")
    if body.node not in NODE_ORDER:
        raise RunError(f"unknown node {body.node}; known: {', '.join(NODE_ORDER)}")
    _submit(request, run_id, runtime.rerun_from, run_id, body.node)
    _audit(platform, request, principal, "run.rerun", run_id, node=body.node)
    return {"run_id": run_id, "status": "running", "from_node": body.node}


# ── state, events, artifacts ─────────────────────────────────────────────────


@router.get("/runs/{run_id}/state")
def get_state(run_id: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    return runtime.get_state(run_id)


@router.patch("/runs/{run_id}/state")
def patch_state(run_id: str, body: PatchStateBody, request: Request, runtime: MigrationRuntime = Depends(get_runtime), platform: Platform = Depends(get_platform), principal: Principal = Depends(require_role("operator"))) -> dict[str, Any]:
    record = runtime.patch_state(run_id, body.values)
    _audit(platform, request, principal, "run.state_patched", run_id, keys=sorted(body.values))
    return record.to_dict()


@router.get("/runs/{run_id}/events")
def events(run_id: str, since: int = 0, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> list[dict[str, Any]]:
    return runtime.events(run_id, since=since)


@router.get("/runs/{run_id}/events/stream")
def stream_events(run_id: str, request: Request, since: int = 0, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> StreamingResponse:
    runtime.get_run(run_id)  # 404 early

    def generate() -> Iterator[str]:
        cursor = since
        idle_ticks = 0
        while True:
            batch = runtime.events(run_id, since=cursor)
            for event in batch:
                yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"
            cursor += len(batch)
            record = runtime.get_run(run_id)
            executing = _executing(request, run_id)
            if not batch and not executing and (record.status in TERMINAL_STATUSES or record.status == "paused"):
                yield f"event: done\ndata: {json.dumps({'status': record.status})}\n\n"
                return
            idle_ticks = idle_ticks + 1 if not batch else 0
            if idle_ticks % 8 == 7:  # every ~4 s of silence
                yield ": keep-alive\n\n"
            time.sleep(0.5)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/runs/{run_id}/artifacts")
def artifacts(run_id: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> list[dict[str, Any]]:
    return runtime.artifacts(run_id)


@router.get("/runs/{run_id}/artifacts/archive")
def artifacts_archive(run_id: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> Response:
    files = runtime.artifacts(run_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            archive.writestr(item["path"], runtime.read_artifact(run_id, item["path"]))
    buffer.seek(0)
    return Response(buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{run_id}-artifacts.zip"'})


@router.get("/runs/{run_id}/artifacts/{path:path}", response_class=PlainTextResponse)
def artifact(run_id: str, path: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> str:
    try:
        return runtime.read_artifact(run_id, path)
    except RunError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/diff/{other_id}")
def diff_runs(run_id: str, other_id: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    """Unified diffs of the generated Terraform between two runs (left: other, right: this)."""
    left = {item["path"]: runtime.read_artifact(other_id, item["path"]) for item in runtime.artifacts(other_id) if item["path"].endswith(".tf")}
    right = {item["path"]: runtime.read_artifact(run_id, item["path"]) for item in runtime.artifacts(run_id) if item["path"].endswith(".tf")}
    files: list[dict[str, Any]] = []
    for path in sorted(set(left) | set(right)):
        before, after = left.get(path), right.get(path)
        if before is None:
            status = "added"
        elif after is None:
            status = "removed"
        elif before == after:
            status = "same"
        else:
            status = "modified"
        diff = ""
        if status != "same":
            diff = "".join(difflib.unified_diff((before or "").splitlines(True), (after or "").splitlines(True), fromfile=f"{other_id}/{path}", tofile=f"{run_id}/{path}"))
        files.append({"path": path, "status": status, "diff": diff})
    summary = Counter(item["status"] for item in files)
    return {"run_id": run_id, "other_id": other_id, "files": files, "summary": dict(summary)}


@router.get("/runs/{run_id}/compliance")
def compliance(run_id: str, runtime: MigrationRuntime = Depends(get_runtime), _: Principal = Depends(require_role("viewer"))) -> dict[str, Any]:
    try:
        return json.loads(runtime.read_artifact(run_id, "compliance_report.json"))
    except RunError:
        pass
    state = runtime.get_state(run_id)
    result = state.get("values", {}).get("compliance_result")
    if isinstance(result, dict):
        return result
    raise HTTPException(status_code=404, detail="no compliance report for this run yet")
