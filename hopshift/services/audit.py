"""Tamper-evident audit log.

Every entry stores the hash of the previous entry and its own hash over the canonical JSON of
its fields, so a modified or deleted row breaks the chain. `verify()` recomputes the chain and
reports the first broken entry. Evidence for SOC 2 CC7.2 / CC4.1 and HIPAA 164.312(b).
Details must never contain secrets; callers pass identifiers and outcomes only.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from hopshift.services.db import Database, register_migration

register_migration(
    "audit_001_log",
    """
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      actor TEXT NOT NULL,
      actor_kind TEXT NOT NULL,
      action TEXT NOT NULL,
      target_type TEXT,
      target_id TEXT,
      outcome TEXT NOT NULL,
      ip TEXT,
      user_agent TEXT,
      details TEXT NOT NULL,
      prev_hash TEXT NOT NULL,
      hash TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS audit_log_ts ON audit_log(ts);
    CREATE INDEX IF NOT EXISTS audit_log_action ON audit_log(action);
    CREATE INDEX IF NOT EXISTS audit_log_actor ON audit_log(actor);
    CREATE INDEX IF NOT EXISTS audit_log_target ON audit_log(target_type, target_id);
    """,
)

GENESIS_HASH = "0" * 64


@dataclass
class AuditEntry:
    id: int
    ts: str
    actor: str
    actor_kind: str
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    ip: str | None
    user_agent: str | None
    details: dict[str, Any]
    prev_hash: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditVerification:
    ok: bool
    entries: int
    broken_at: int | None = None
    message: str = ""


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(fields)).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        *,
        actor: str = "system",
        actor_kind: str = "system",
        target_type: str | None = None,
        target_id: str | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuditEntry:
        fields = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "actor": actor,
            "actor_kind": actor_kind,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "ip": ip,
            "user_agent": (user_agent or "")[:300] or None,
            "details": details or {},
        }
        with self._lock, self.db.connect() as conn:
            row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = row["hash"] if row else GENESIS_HASH
            digest = compute_hash(prev_hash, fields)
            cursor = conn.execute(
                "INSERT INTO audit_log (ts, actor, actor_kind, action, target_type, target_id, outcome, ip, user_agent,"
                " details, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fields["ts"], actor, actor_kind, action, target_type, target_id, outcome, ip,
                    fields["user_agent"], _canonical(fields["details"]), prev_hash, digest,
                ),
            )
            entry_id = int(cursor.lastrowid or 0)
        return AuditEntry(id=entry_id, prev_hash=prev_hash, hash=digest, **fields)

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        action: str | None = None,
        actor: str | None = None,
        since: str | None = None,
        target_id: str | None = None,
        target_type: str | None = None,
        outcome: str | None = None,
    ) -> tuple[list[AuditEntry], int]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("action", action), ("actor", actor), ("target_id", target_id), ("target_type", target_type), ("outcome", outcome)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM audit_log{where}", params).fetchone()[0])
            rows = conn.execute(
                f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, max(1, min(limit, 1000)), max(0, offset)],
            ).fetchall()
        return [self._row_to_entry(row) for row in rows], total

    def iter_all(self) -> Iterator[AuditEntry]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        for row in rows:
            yield self._row_to_entry(row)

    def verify(self) -> AuditVerification:
        prev_hash = GENESIS_HASH
        count = 0
        for entry in self.iter_all():
            count += 1
            fields = {
                "ts": entry.ts, "actor": entry.actor, "actor_kind": entry.actor_kind, "action": entry.action,
                "target_type": entry.target_type, "target_id": entry.target_id, "outcome": entry.outcome,
                "ip": entry.ip, "user_agent": entry.user_agent, "details": entry.details,
            }
            if entry.prev_hash != prev_hash:
                return AuditVerification(False, count, entry.id, f"entry {entry.id} does not chain to its predecessor")
            if compute_hash(prev_hash, fields) != entry.hash:
                return AuditVerification(False, count, entry.id, f"entry {entry.id} has been altered")
            prev_hash = entry.hash
        return AuditVerification(True, count, None, "chain intact")

    def prune_before(self, iso_timestamp: str) -> int:
        """Retention: remove entries older than the timestamp. Pruning re-anchors the chain, so the
        action itself is recorded afterwards with the number of removed rows."""
        with self._lock, self.db.connect() as conn:
            cursor = conn.execute("DELETE FROM audit_log WHERE ts < ?", (iso_timestamp,))
            removed = int(cursor.rowcount or 0)
            first = conn.execute("SELECT id, prev_hash FROM audit_log ORDER BY id ASC LIMIT 1").fetchone()
            if first is not None and first["prev_hash"] != GENESIS_HASH:
                # Re-anchor: the oldest surviving row becomes the genesis of the chain.
                self._reanchor(conn)
        if removed:
            self.record("audit.pruned", details={"removed": removed, "before": iso_timestamp})
        return removed

    def _reanchor(self, conn: Any) -> None:
        prev_hash = GENESIS_HASH
        for row in conn.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall():
            entry = self._row_to_entry(row)
            fields = {
                "ts": entry.ts, "actor": entry.actor, "actor_kind": entry.actor_kind, "action": entry.action,
                "target_type": entry.target_type, "target_id": entry.target_id, "outcome": entry.outcome,
                "ip": entry.ip, "user_agent": entry.user_agent, "details": entry.details,
            }
            digest = compute_hash(prev_hash, fields)
            conn.execute("UPDATE audit_log SET prev_hash = ?, hash = ? WHERE id = ?", (prev_hash, digest, entry.id))
            prev_hash = digest

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        return AuditEntry(
            id=int(row["id"]), ts=row["ts"], actor=row["actor"], actor_kind=row["actor_kind"], action=row["action"],
            target_type=row["target_type"], target_id=row["target_id"], outcome=row["outcome"], ip=row["ip"],
            user_agent=row["user_agent"], details=json.loads(row["details"] or "{}"), prev_hash=row["prev_hash"],
            hash=row["hash"],
        )
