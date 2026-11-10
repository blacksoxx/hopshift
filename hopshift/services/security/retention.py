"""Retention sweeps: delete old runs and prune old audit entries.

`security.retention.runs_days` and `audit_days` (0 keeps everything; both editable from the
settings UI). Runs are deleted through `MigrationRuntime.delete_run()` so checkpoints go with
them; running and paused runs are never touched. Audit pruning goes through
`AuditLog.prune_before()`, which re-anchors the hash chain and records the prune itself.
Evidence for SOC 2 CC6.5 and HIPAA 164.310(d)(2)(i).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

PROTECTED_STATUSES = frozenset({"running", "paused"})
DEFAULT_INTERVAL_SECONDS = 3600


def _retention_cfg(platform: Any) -> tuple[int, int]:
    config = platform.effective_config()
    security = config.get("security") if isinstance(config.get("security"), dict) else {}
    retention = security.get("retention") if isinstance(security.get("retention"), dict) else {}
    try:
        runs_days = max(0, int(retention.get("runs_days") or 0))
    except (TypeError, ValueError):
        runs_days = 0
    try:
        audit_days = max(0, int(retention.get("audit_days") or 0))
    except (TypeError, ValueError):
        audit_days = 0
    return runs_days, audit_days


def sweep(
    platform: Any,
    runtime: Any,
    dry_run: bool = False,
    *,
    actor: str = "system",
    runs_days: int | None = None,
    include_audit: bool = True,
) -> dict[str, int]:
    """Apply the retention policy once. `runs_days` overrides the configured value and
    `include_audit=False` leaves the audit log alone (CLI `runs prune`)."""
    cfg_runs_days, audit_days = _retention_cfg(platform)
    if not include_audit:
        audit_days = 0
    effective_runs_days = cfg_runs_days if runs_days is None else max(0, int(runs_days))
    now = datetime.now(timezone.utc)
    runs_deleted = 0
    if effective_runs_days > 0 and runtime is not None:
        cutoff = (now - timedelta(days=effective_runs_days)).isoformat(timespec="seconds")
        for record in runtime.list_runs():
            if record.status in PROTECTED_STATUSES:
                continue
            stamp = record.updated_at or record.created_at
            if stamp >= cutoff:
                continue
            if not dry_run:
                try:
                    runtime.delete_run(record.run_id)
                except Exception as exc:  # a run being executed right now, or a half-deleted folder
                    logger.warning("retention: could not delete run {}: {}", record.run_id, exc)
                    continue
            runs_deleted += 1
    audit_pruned = 0
    if audit_days > 0:
        cutoff_audit = (now - timedelta(days=audit_days)).isoformat(timespec="milliseconds")
        if dry_run:
            with platform.db.connect() as conn:
                audit_pruned = int(conn.execute("SELECT COUNT(*) FROM audit_log WHERE ts < ?", (cutoff_audit,)).fetchone()[0])
        else:
            audit_pruned = platform.audit.prune_before(cutoff_audit)
    result = {"runs_deleted": runs_deleted, "audit_pruned": audit_pruned}
    if not dry_run and (runs_deleted or audit_pruned):
        platform.audit.record(
            "retention.sweep", actor=actor, actor_kind="system" if actor == "system" else "user", target_type="retention",
            details={**result, "runs_days": effective_runs_days, "audit_days": audit_days},
        )
        logger.info("retention: deleted {} run(s), pruned {} audit entr(ies)", runs_deleted, audit_pruned)
    return result


def start_background_sweeper(app: Any, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> threading.Thread | None:
    """Run `sweep` hourly in a daemon thread for the life of the app. Idempotent per app."""
    if getattr(app.state, "retention_thread", None) is not None:
        return app.state.retention_thread
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval_seconds):
            platform = getattr(app.state, "platform", None)
            runtime = getattr(app.state, "runtime", None)
            if platform is None:
                continue
            try:
                sweep(platform, runtime)
                housekeeping = getattr(getattr(platform, "auth", None), "housekeeping", None)
                if callable(housekeeping):
                    housekeeping()  # drop revoked/expired sessions and week-old login attempts
            except Exception as exc:  # pragma: no cover - defensive; the loop must survive
                logger.warning("retention: sweep failed: {}", exc)

    thread = threading.Thread(target=loop, name="hopshift-retention", daemon=True)
    app.state.retention_stop = stop
    app.state.retention_thread = thread
    thread.start()
    return thread


def stop_background_sweeper(app: Any) -> None:
    stop = getattr(app.state, "retention_stop", None)
    if stop is not None:
        stop.set()
    app.state.retention_thread = None
    app.state.retention_stop = None
