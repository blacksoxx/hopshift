"""SQLite access with a tiny migration registry.

Every service registers its schema at import time with `register_migration(name, sql)`;
`Database.migrate()` applies the registered statements once, in registration order, and
records them in `schema_migrations`. Connections are short-lived: open one per unit of work
with `with db.connect() as conn:`; the context commits on success and rolls back on error.
WAL mode lets readers and a writer overlap, which is what the API's thread pool needs.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Migration:
    name: str
    sql: str


_MIGRATIONS: list[Migration] = []
_REGISTRY_LOCK = threading.Lock()


def register_migration(name: str, sql: str) -> None:
    """Register a schema change. Names must be unique and stable (they are recorded in the db)."""
    with _REGISTRY_LOCK:
        if any(item.name == name for item in _MIGRATIONS):
            return
        _MIGRATIONS.append(Migration(name=name, sql=sql))


def registered_migrations() -> list[Migration]:
    with _REGISTRY_LOCK:
        return list(_MIGRATIONS)


class Database:
    """A SQLite database file (or ':memory:' for tests that do not need persistence)."""

    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path).expanduser() if path and str(path) != ":memory:" else None
        self._memory_conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.path is None:
            # One shared in-memory connection, serialised by the lock.
            with self._lock:
                if self._memory_conn is None:
                    self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                    self._memory_conn.row_factory = sqlite3.Row
                    self._memory_conn.execute("PRAGMA foreign_keys = ON")
                conn = self._memory_conn
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            return

        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> list[str]:
        """Apply every registered migration not yet recorded. Returns the names applied."""
        applied: list[str] = []
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
            for migration in registered_migrations():
                if migration.name in done:
                    continue
                conn.executescript(migration.sql)
                conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (migration.name,))
                applied.append(migration.name)
        return applied

    def table_names(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()
        return [row["name"] for row in rows]
