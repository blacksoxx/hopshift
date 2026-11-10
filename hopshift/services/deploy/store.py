"""Deployment records: a row per plan / apply / destroy in SQLite, mirrored to deployment.json.

The SQLite row is the source of truth for listing and the active-deployment check; the JSON
mirror under `<run_dir>/deploy/<deployment_id>/` keeps the run folder self-describing.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from hopshift.services.db import Database, register_migration

register_migration(
    "deploy_001_deployments",
    """
    CREATE TABLE IF NOT EXISTS deployments (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL,
      action TEXT NOT NULL,
      status TEXT NOT NULL,
      connection_id TEXT,
      connection_name TEXT,
      provider TEXT,
      requested_by TEXT NOT NULL,
      approved_by TEXT,
      plan_id TEXT,
      created_at TEXT NOT NULL,
      started_at TEXT,
      finished_at TEXT,
      exit_code INTEGER,
      summary TEXT,
      error TEXT,
      log_path TEXT NOT NULL,
      artifacts_hash TEXT
    );
    CREATE INDEX IF NOT EXISTS deployments_run ON deployments(run_id, created_at);
    CREATE INDEX IF NOT EXISTS deployments_status ON deployments(status);
    """,
)

ACTIONS: tuple[str, ...] = ("plan", "apply", "destroy")
ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})


@dataclass
class Deployment:
    id: str
    run_id: str
    action: str
    status: str
    connection_id: str | None
    connection_name: str | None
    provider: str | None
    requested_by: str
    approved_by: str | None
    plan_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    summary: dict[str, Any] | None
    error: str | None
    log_path: str
    artifacts_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Deployment":
        data = {key: row[key] for key in row.keys()}
        raw_summary = data.get("summary")
        data["summary"] = json.loads(raw_summary) if raw_summary else None
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def new_deployment_id() -> str:
    return uuid.uuid4().hex


class DeploymentStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(self, deployment: Deployment) -> None:
        data = deployment.to_dict()
        data["summary"] = json.dumps(data["summary"]) if data["summary"] is not None else None
        columns = list(data)
        with self.db.connect() as conn:
            conn.execute(
                f"INSERT INTO deployments ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [data[column] for column in columns],
            )

    def update(self, deployment_id: str, **values: Any) -> None:
        if not values:
            return
        if "summary" in values and values["summary"] is not None:
            values["summary"] = json.dumps(values["summary"])
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE deployments SET {assignments} WHERE id = ?", [*values.values(), deployment_id])

    def get(self, deployment_id: str) -> Deployment | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
        return Deployment.from_row(row) if row else None

    def list(self, run_id: str) -> list[Deployment]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM deployments WHERE run_id = ? ORDER BY created_at DESC, rowid DESC", (run_id,)
            ).fetchall()
        return [Deployment.from_row(row) for row in rows]

    def active_for(self, run_id: str) -> Deployment | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM deployments WHERE run_id = ? AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return Deployment.from_row(row) if row else None

    def fail_interrupted(self, finished_at: str) -> int:
        """Rows left queued/running by a previous process can never finish: mark them failed."""
        try:
            with self.db.connect() as conn:
                cursor = conn.execute(
                    "UPDATE deployments SET status = 'failed', finished_at = ?, error = ? WHERE status IN ('queued', 'running')",
                    (finished_at, "interrupted: the platform restarted while this deployment was active"),
                )
                return int(cursor.rowcount or 0)
        except sqlite3.OperationalError:
            return 0  # schema not migrated yet (service constructed before Database.migrate)


def write_mirror(path: Path, deployment: Deployment) -> None:
    """Atomically write deployment.json next to the log so the run folder is self-describing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(deployment.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
