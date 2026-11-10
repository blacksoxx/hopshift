"""SQLite persistence for connections and device flows.

Secrets are stored only as Fernet tokens produced by hopshift.services.secrets.SecretBox; the store never
sees plaintext. `secret_keys` holds the names of the stored secret fields so listings can
report `has_secret` / `secret_fields` without decrypting.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from hopshift.services.db import Database, register_migration
from hopshift.services.errors import Conflict, NotFound

from .models import Connection

register_migration(
    "connections_001_connections",
    """
    CREATE TABLE IF NOT EXISTS connections (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL UNIQUE COLLATE NOCASE,
      provider TEXT NOT NULL,
      auth_method TEXT NOT NULL,
      config TEXT NOT NULL,
      secret_token TEXT,
      secret_keys TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'unverified',
      last_checked_at TEXT,
      last_check TEXT,
      created_by TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS connections_provider ON connections(provider);
    """,
)

register_migration(
    "connections_002_device_flows",
    """
    CREATE TABLE IF NOT EXISTS device_flows (
      flow_id TEXT PRIMARY KEY,
      connection_id TEXT NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
      provider TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      secret_token TEXT
    );
    CREATE INDEX IF NOT EXISTS device_flows_connection ON device_flows(connection_id);
    """,
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class DeviceFlow:
    flow_id: str
    connection_id: str
    provider: str
    created_at: str
    expires_at: str
    status: str
    payload: dict[str, Any]
    secret_token: str | None

    @property
    def expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.expires_at) <= datetime.now(timezone.utc)
        except ValueError:
            return True


class ConnectionStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ── connections ───────────────────────────────────────────────────────

    def list(self) -> list[Connection]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM connections ORDER BY name COLLATE NOCASE").fetchall()
        return [_row_to_connection(row) for row in rows]

    def get(self, connection_id: str) -> Connection:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            raise NotFound(f"unknown connection {connection_id}")
        return _row_to_connection(row)

    def find_by_name(self, name: str) -> Connection | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM connections WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        return _row_to_connection(row) if row is not None else None

    def insert(self, connection: Connection) -> Connection:
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO connections (id, name, provider, auth_method, config, secret_token, secret_keys, status,"
                    " last_checked_at, last_check, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        connection.id, connection.name, connection.provider, connection.auth_method,
                        _dump(connection.config), connection.secret_token, _dump(sorted(connection.secret_keys)),
                        connection.status, connection.last_checked_at, _dump(connection.last_check) if connection.last_check is not None else None,
                        connection.created_by, connection.created_at, connection.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"a connection named {connection.name!r} already exists") from exc
        return connection

    def update(self, connection: Connection) -> Connection:
        try:
            with self.db.connect() as conn:
                cursor = conn.execute(
                    "UPDATE connections SET name = ?, config = ?, secret_token = ?, secret_keys = ?, status = ?,"
                    " last_checked_at = ?, last_check = ?, updated_at = ? WHERE id = ?",
                    (
                        connection.name, _dump(connection.config), connection.secret_token, _dump(sorted(connection.secret_keys)),
                        connection.status, connection.last_checked_at,
                        _dump(connection.last_check) if connection.last_check is not None else None,
                        connection.updated_at, connection.id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict(f"a connection named {connection.name!r} already exists") from exc
        if cursor.rowcount == 0:
            raise NotFound(f"unknown connection {connection.id}")
        return connection

    def set_check(self, connection_id: str, status: str, checked_at: str, last_check: dict[str, Any]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE connections SET status = ?, last_checked_at = ?, last_check = ? WHERE id = ?",
                (status, checked_at, _dump(last_check), connection_id),
            )

    def set_secret(self, connection_id: str, secret_token: str | None, secret_keys: list[str]) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE connections SET secret_token = ?, secret_keys = ?, updated_at = ? WHERE id = ?",
                (secret_token, _dump(sorted(secret_keys)), utcnow(), connection_id),
            )

    def delete(self, connection_id: str) -> None:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        if cursor.rowcount == 0:
            raise NotFound(f"unknown connection {connection_id}")

    def encrypted_tokens(self) -> list[tuple[str, str, str]]:
        """Every (table, id, token) pair holding an encrypted secret, for key rotation."""
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id, secret_token FROM connections WHERE secret_token IS NOT NULL").fetchall()
            flows = conn.execute("SELECT flow_id, secret_token FROM device_flows WHERE secret_token IS NOT NULL").fetchall()
        return [("connections", row["id"], row["secret_token"]) for row in rows] + [("device_flows", row["flow_id"], row["secret_token"]) for row in flows]

    def replace_token(self, table: str, row_id: str, token: str) -> None:
        if table not in {"connections", "device_flows"}:
            raise ValueError(f"unknown table {table}")
        key = "id" if table == "connections" else "flow_id"
        with self.db.connect() as conn:
            conn.execute(f"UPDATE {table} SET secret_token = ? WHERE {key} = ?", (token, row_id))

    # ── device flows ──────────────────────────────────────────────────────

    def insert_flow(self, flow: DeviceFlow) -> DeviceFlow:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO device_flows (flow_id, connection_id, provider, created_at, expires_at, status, payload, secret_token)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (flow.flow_id, flow.connection_id, flow.provider, flow.created_at, flow.expires_at, flow.status, _dump(flow.payload), flow.secret_token),
            )
        return flow

    def get_flow(self, flow_id: str) -> DeviceFlow:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM device_flows WHERE flow_id = ?", (flow_id,)).fetchone()
        if row is None:
            raise NotFound(f"unknown device flow {flow_id}")
        return DeviceFlow(
            flow_id=row["flow_id"], connection_id=row["connection_id"], provider=row["provider"], created_at=row["created_at"],
            expires_at=row["expires_at"], status=row["status"], payload=json.loads(row["payload"] or "{}"), secret_token=row["secret_token"],
        )

    def set_flow_status(self, flow_id: str, status: str, payload: dict[str, Any] | None = None, *, clear_secret: bool = False) -> None:
        with self.db.connect() as conn:
            if payload is not None:
                conn.execute("UPDATE device_flows SET status = ?, payload = ? WHERE flow_id = ?", (status, _dump(payload), flow_id))
            else:
                conn.execute("UPDATE device_flows SET status = ? WHERE flow_id = ?", (status, flow_id))
            if clear_secret:
                conn.execute("UPDATE device_flows SET secret_token = NULL WHERE flow_id = ?", (flow_id,))

    def prune_flows(self, before: str) -> int:
        with self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM device_flows WHERE expires_at < ? AND status != 'pending'", (before,))
        return int(cursor.rowcount or 0)


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def _row_to_connection(row: Any) -> Connection:
    return Connection(
        id=row["id"], name=row["name"], provider=row["provider"], auth_method=row["auth_method"],
        config=json.loads(row["config"] or "{}"), secret_token=row["secret_token"], secret_keys=json.loads(row["secret_keys"] or "[]"),
        status=row["status"], last_checked_at=row["last_checked_at"],
        last_check=json.loads(row["last_check"]) if row["last_check"] else None,
        created_by=row["created_by"], created_at=row["created_at"], updated_at=row["updated_at"],
    )
