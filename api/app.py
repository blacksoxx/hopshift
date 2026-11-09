"""FastAPI application factory.

Every write path goes through agent.runtime.MigrationRuntime (runs) or a vma service
(connections, deployments, users), so the same guards apply as for the CLI. API routes live
under /api; the built UI (ui/dist) is served at /. Runs execute in a thread pool; clients poll
or subscribe to server-sent events.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from agent.config_loader import load_config
from agent.runtime import MigrationRuntime, RunError
from api.middleware import OriginCheckMiddleware, SecurityHeadersMiddleware
from api.routes import all_routers
from vma import __version__
from vma.errors import Conflict, Forbidden, Invalid, NotFound, PlatformError, Unavailable
from vma.platform import Platform
from vma.secrets import SecretsUnavailable
from vma.settings import SettingsError

UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"


def create_app(
    runtime: MigrationRuntime | None = None,
    config_path: str | Path = "config.yaml",
    ui_dir: Path | str | None = None,
    platform: Platform | None = None,
    platform_db: Path | str | None = None,
) -> FastAPI:
    """Build the application.

    `runtime` and `platform` are injectable for tests. When only `runtime` is given, the platform
    is created from the runtime's config with an in-memory database.
    """
    if runtime is None:
        base_config = load_config(config_path)
        platform = platform or Platform.from_config(base_config, db_path=platform_db)
        runtime = MigrationRuntime(platform.effective_config())
    elif platform is None:
        platform = Platform.from_config(runtime.base_config, db_path=platform_db or ":memory:")
        runtime.base_config = platform.effective_config()

    security_cfg = platform.config.get("security") if isinstance(platform.config.get("security"), dict) else {}
    headers_cfg = security_cfg.get("headers") if isinstance(security_cfg.get("headers"), dict) else {}
    docs_enabled = bool(security_cfg.get("api_docs", True))

    app = FastAPI(
        title="vmware-migration-agent",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.runtime = runtime
    app.state.platform = platform
    app.state.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vma-run")
    app.state.futures: dict[str, Future[Any]] = {}

    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=bool(headers_cfg.get("hsts", True)),
        csp_mode=str(headers_cfg.get("content_security_policy", "default")),
    )
    app.add_middleware(OriginCheckMiddleware, allowed_origins=[str(item) for item in (security_cfg.get("allowed_origins") or [])])
    if platform.auth is not None and hasattr(platform.auth, "install_middleware"):
        platform.auth.install_middleware(app)

    @app.exception_handler(RunError)
    async def _run_error(request: Request, exc: RunError):  # type: ignore[no-untyped-def]
        status = 404 if str(exc).startswith("unknown run") else 400
        return PlainTextResponse(str(exc), status_code=status)

    @app.exception_handler(SettingsError)
    async def _settings_error(request: Request, exc: SettingsError):  # type: ignore[no-untyped-def]
        return PlainTextResponse(str(exc), status_code=400)

    @app.exception_handler(SecretsUnavailable)
    async def _secrets_error(request: Request, exc: SecretsUnavailable):  # type: ignore[no-untyped-def]
        return PlainTextResponse(str(exc), status_code=503)

    @app.exception_handler(PlatformError)
    async def _platform_error(request: Request, exc: PlatformError):  # type: ignore[no-untyped-def]
        status = {NotFound: 404, Conflict: 409, Forbidden: 403, Invalid: 400, Unavailable: 503}.get(type(exc), 400)
        return PlainTextResponse(str(exc), status_code=status)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # type: ignore[no-untyped-def]
        return PlainTextResponse(str(exc), status_code=400)

    for router in all_routers():
        app.include_router(router, prefix="/api")

    static_dir = Path(ui_dir) if ui_dir is not None else UI_DIST
    if static_dir.is_dir():
        # Mounted last so /api/* wins; html=True serves index.html for / (the UI uses hash routes).
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")

    return app


def submit_run(app: FastAPI, run_id: str, fn: Any, *args: Any) -> None:
    """Execute a runtime action for a run in the pool; one in-flight execution per run."""
    future = app.state.futures.get(run_id)
    if future is not None and not future.done():
        raise HTTPException(status_code=409, detail=f"run {run_id} is already executing")
    app.state.futures[run_id] = app.state.executor.submit(fn, *args)


def is_executing(app: FastAPI, run_id: str) -> bool:
    future = app.state.futures.get(run_id)
    return bool(future is not None and not future.done())


# No module-level application: importing this module must not touch the filesystem or the
# database. Serve with `vma serve`, or with uvicorn's factory mode:
#   uvicorn --factory api.app:create_app
