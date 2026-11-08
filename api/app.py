"""FastAPI surface for the migration runtime.

Every write path goes through agent.runtime.MigrationRuntime, so the same guards apply as for
the CLI. Runs execute in a background thread; clients poll GET /runs/{id} or subscribe to the
SSE event stream.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.config_loader import load_config
from agent.graph import NODE_ORDER
from agent.runtime import GENERATION_MODES, PAUSE_POINTS, MigrationRuntime, RunError, RunOptions, initial_state
from cim.schema import TargetProvider

TERMINAL_STATUSES = {"succeeded", "failed", "error"}


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


class PatchStateBody(BaseModel):
    values: dict[str, Any]


class RerunBody(BaseModel):
    node: str


class AssessBody(BaseModel):
    discovery: dict[str, Any]
    cloud: str


UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"


def create_app(
    runtime: MigrationRuntime | None = None,
    config_path: str | Path = "config.yaml",
    ui_dir: Path | str | None = None,
) -> FastAPI:
    """Build the application. API routes live under /api; the built UI (ui/dist) is served at /."""
    app = FastAPI(title="vmware-migration-agent", version="0.2.0")
    router = APIRouter(prefix="/api")
    app.state.runtime = runtime or MigrationRuntime(load_config(config_path))
    app.state.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vma-run")
    app.state.futures: dict[str, Future[Any]] = {}

    def rt() -> MigrationRuntime:
        return app.state.runtime

    def submit(run_id: str, fn: Any, *args: Any) -> None:
        future = app.state.futures.get(run_id)
        if future is not None and not future.done():
            raise HTTPException(status_code=409, detail=f"run {run_id} is already executing")
        app.state.futures[run_id] = app.state.executor.submit(fn, *args)

    @app.exception_handler(RunError)
    async def _run_error(request: Request, exc: RunError):  # type: ignore[no-untyped-def]
        status = 404 if str(exc).startswith("unknown run") else 400
        return PlainTextResponse(str(exc), status_code=status)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # type: ignore[no-untyped-def]
        return PlainTextResponse(str(exc), status_code=400)

    # ── meta ──────────────────────────────────────────────────────────────────

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "runs_dir": str(rt().store.root)}

    @router.get("/meta")
    def meta() -> dict[str, Any]:
        return {
            "clouds": [provider.value for provider in TargetProvider],
            "modes": list(GENERATION_MODES),
            "pause_points": PAUSE_POINTS,
            "nodes": list(NODE_ORDER),
            "default_pause_points": rt().default_pause_points,
        }

    @router.get("/config")
    def config() -> dict[str, Any]:
        return _jsonable(rt().base_config)

    # ── runs ──────────────────────────────────────────────────────────────────

    @router.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        return [record.to_dict() for record in rt().list_runs()]

    @router.post("/runs", status_code=201)
    def create_run(body: CreateRunBody) -> dict[str, Any]:
        record = rt().create_run(body.discovery, body.options.to_options(), input_filename=body.input_filename)
        if body.start:
            submit(record.run_id, rt().start, record.run_id)
            record.status = "running"
        return record.to_dict()

    @router.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        record = rt().get_run(run_id)
        payload = record.to_dict()
        future = app.state.futures.get(run_id)
        payload["executing"] = bool(future is not None and not future.done())
        return payload

    @router.post("/runs/{run_id}/start", status_code=202)
    def start_run(run_id: str) -> dict[str, Any]:
        record = rt().get_run(run_id)
        if record.status != "created":
            raise RunError(f"run {run_id} is {record.status}; only a created run can be started")
        submit(run_id, rt().start, run_id)
        return {"run_id": run_id, "status": "running"}

    @router.post("/runs/{run_id}/resume", status_code=202)
    def resume_run(run_id: str) -> dict[str, Any]:
        record = rt().get_run(run_id)
        if record.status != "paused":
            raise RunError(f"run {run_id} is {record.status}; only a paused run can be resumed")
        submit(run_id, rt().resume, run_id)
        return {"run_id": run_id, "status": "running", "resumed_from": record.pause_point}

    @router.post("/runs/{run_id}/rerun", status_code=202)
    def rerun(run_id: str, body: RerunBody) -> dict[str, Any]:
        record = rt().get_run(run_id)
        if record.status in {"running", "created"}:
            raise RunError(f"run {run_id} is {record.status}; it cannot be re-run yet")
        if body.node not in NODE_ORDER:
            raise RunError(f"unknown node {body.node}; known: {', '.join(NODE_ORDER)}")
        submit(run_id, rt().rerun_from, run_id, body.node)
        return {"run_id": run_id, "status": "running", "from_node": body.node}

    @router.get("/runs/{run_id}/state")
    def get_state(run_id: str) -> dict[str, Any]:
        return rt().get_state(run_id)

    @router.patch("/runs/{run_id}/state")
    def patch_state(run_id: str, body: PatchStateBody) -> dict[str, Any]:
        return rt().patch_state(run_id, body.values).to_dict()

    @router.get("/runs/{run_id}/events")
    def events(run_id: str, since: int = 0) -> list[dict[str, Any]]:
        return rt().events(run_id, since=since)

    @router.get("/runs/{run_id}/events/stream")
    def stream_events(run_id: str, since: int = 0) -> StreamingResponse:
        rt().get_run(run_id)  # 404 early

        def generate() -> Iterator[str]:
            cursor = since
            idle_ticks = 0
            while True:
                batch = rt().events(run_id, since=cursor)
                for event in batch:
                    yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"
                cursor += len(batch)
                record = rt().get_run(run_id)
                future = app.state.futures.get(run_id)
                executing = bool(future is not None and not future.done())
                if not batch and not executing and (record.status in TERMINAL_STATUSES or record.status == "paused"):
                    yield f"event: done\ndata: {json.dumps({'status': record.status})}\n\n"
                    return
                idle_ticks = idle_ticks + 1 if not batch else 0
                if idle_ticks % 8 == 7:  # every ~4 s of silence
                    yield ": keep-alive\n\n"
                time.sleep(0.5)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.get("/runs/{run_id}/artifacts")
    def artifacts(run_id: str) -> list[dict[str, Any]]:
        return rt().artifacts(run_id)

    @router.get("/runs/{run_id}/artifacts/{path:path}", response_class=PlainTextResponse)
    def artifact(run_id: str, path: str) -> str:
        try:
            return rt().read_artifact(run_id, path)
        except RunError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ── assessment (synchronous, no cloud or LLM access) ──────────────────────

    @router.post("/assess")
    def assess(body: AssessBody) -> dict[str, Any]:
        from agent.graph import build_assess_graph
        from agent.runtime import build_run_config

        options = RunOptions(cloud=body.cloud, environment="assess", owner="assess", dry_run=True)
        options.validate()
        cfg = build_run_config(rt().base_config, options, rt().store.root / "_assess")
        state = initial_state(body.discovery, cfg, body.cloud)
        final = build_assess_graph().invoke(state)
        return _jsonable(final.get("assessment_result", {}))

    app.include_router(router)

    static_dir = Path(ui_dir) if ui_dir is not None else UI_DIST
    if static_dir.is_dir():
        # Mounted last so /api/* wins; html=True serves index.html for / (the UI uses hash routes).
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")

    return app


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return getattr(value, "value")
    return value


app = create_app()
