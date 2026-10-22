"""SQLite persistence (WAL). Single writer connection guarded by a lock keeps
the codebase small while plenty fast for a local-first tool."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._migrate()

    # -- schema ------------------------------------------------------------
    def _migrate(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    agent TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    parent_event_id TEXT,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session_ts ON events(session_id, ts);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    first_ts REAL NOT NULL,
                    last_ts REAL NOT NULL,
                    end_ts REAL,
                    pid INTEGER,
                    ppid INTEGER,
                    model TEXT,
                    prompt_count INTEGER NOT NULL DEFAULT 0,
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    llm_calls INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    last_iteration INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    metric TEXT,
                    value REAL,
                    limit_value REAL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_ts REAL NOT NULL,
                    resolved_ts REAL,
                    decision_by TEXT,
                    enforcement TEXT
                );
                CREATE TABLE IF NOT EXISTS kv (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # -- execution ---------------------------------------------------------
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "agent": row["agent"],
        "session_id": row["session_id"],
        "type": row["type"],
        "parent_event_id": row["parent_event_id"],
        "data": json.loads(row["data"] or "{}"),
    }
