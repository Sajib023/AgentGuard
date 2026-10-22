"""Event/session queries + approval requests on top of :class:`Database`."""

from __future__ import annotations

import json
import time
from typing import Any

from .db import Database, row_to_event
from .schema import AgentKind, Event, EventType
from .utils import new_id, now


class Store:
    def __init__(self, db: Database):
        self.db = db

    # -- events ------------------------------------------------------------
    def insert(self, event: Event) -> Event:
        """Insert an event; update denormalized session counters in one tx so
        dashboard summaries stay cheap."""
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO events (id, ts, agent, session_id, type, parent_event_id, data) "
                "VALUES (?,?,?,?,?,?,?)",
                (event.id, event.ts, event.agent.value, event.session_id, event.type.value,
                 event.parent_event_id, json.dumps(event.data)),
            )

            data = event.data
            et = event.type
            sets = ["agent=?", "last_ts=?"]
            args: list[Any] = [event.agent.value, event.ts]

            def add(col: str, val: Any) -> None:
                sets.append(f"{col}=?")
                args.append(val)

            if et is EventType.session_start:
                sess = conn.execute(
                    "SELECT 1 FROM sessions WHERE session_id=?", (event.session_id,)
                ).fetchone()
                if not sess:
                    conn.execute(
                        "INSERT INTO sessions (session_id, agent, first_ts, last_ts, pid, ppid, model) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (event.session_id, event.agent.value, event.ts, event.ts,
                         data.get("pid"), data.get("ppid"), data.get("model")),
                    )
                    return
            if et is EventType.session_end:
                add("end_ts", event.ts)
            if et is EventType.prompt_before:
                add("prompt_count", self.count_col(conn, "prompt_count", event.session_id, data) + 1)
            if et is EventType.tool_call:
                add("tool_calls", self.count_col(conn, "tool_calls", event.session_id, data) + 1)
            if et is EventType.llm_call:
                add("llm_calls", self.count_col(conn, "llm_calls", event.session_id, data) + 1)
                for src, dst in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                                 ("cache_read_tokens", "cache_read_tokens"),
                                 ("cache_write_tokens", "cache_write_tokens")):
                    v = int(data.get(src) or 0)
                    if v:
                        add(dst, self.num_col(conn, dst, event.session_id) + v)
                cost = data.get("cost_usd")
                if cost is not None:
                    add("cost_usd", self.num_col(conn, "cost_usd", event.session_id) + float(cost))
                if data.get("iteration") is not None:
                    add("last_iteration", int(data["iteration"]))
            if et is EventType.graph_event and data.get("iteration") is not None:
                add("last_iteration", int(data["iteration"]))
            if event.type in (EventType.state_change,) and data.get("state"):
                model = str(data["state"])
                cur = conn.execute("SELECT model FROM sessions WHERE session_id=?", (event.session_id,)).fetchone()
                if cur and not cur["model"]:
                    add("model", model)

            args.extend([event.session_id])
            conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE session_id=?", tuple(args)
            )

    def count_col(self, conn: Any, col: str, sid: str, data: dict) -> int:
        row = conn.execute(f"SELECT {col} FROM sessions WHERE session_id=?", (sid,)).fetchone()
        return row[col] if row else 0

    def num_col(self, conn: Any, col: str, sid: str) -> float:
        row = conn.execute(f"SELECT {col} FROM sessions WHERE session_id=?", (sid,)).fetchone()
        return float(row[col]) if row else 0.0

    def get_events(
        self,
        *,
        session_id: str | None = None,
        agent: str | None = None,
        type: str | None = None,
        since: float | None = None,
        limit: int = 200,
        order: str = "desc",
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if agent:
            sql += " AND agent=?"
            params.append(agent)
        if type:
            sql += " AND type=?"
            params.append(type)
        if since:
            sql += " AND ts>?"
            params.append(since)
        sql += f" ORDER BY ts {'DESC' if order == 'desc' else 'ASC'} LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        return [Event(**row_to_event(r)) for r in self.db.query(sql, tuple(params))]

    def prune(self, older_than_ts: float) -> int:
        with self.db.tx() as conn:
            cur = conn.execute("DELETE FROM events WHERE ts<?", (older_than_ts,))
            conn.execute("DELETE FROM sessions WHERE last_ts<? AND end_ts IS NULL", (older_than_ts,))
            return cur.rowcount

    # -- sessions ----------------------------------------------------------
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM sessions ORDER BY last_ts DESC LIMIT ?", (max(1, min(limit, 200)),)
        )
        out = []
        for r in rows:
            out.append(
                {
                    "session_id": r["session_id"],
                    "agent": r["agent"],
                    "first_ts": r["first_ts"],
                    "last_ts": r["last_ts"],
                    "end_ts": r["end_ts"],
                    "model": r["model"],
                    "pid": r["pid"],
                    "prompt_count": r["prompt_count"],
                    "tool_calls": r["tool_calls"],
                    "llm_calls": r["llm_calls"],
                    "tokens": r["input_tokens"] + r["output_tokens"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "cost_usd": r["cost_usd"],
                    "iteration": r["last_iteration"],
                }
            )
        return out

    def get_session(self, sid: str) -> dict[str, Any] | None:
        rows = self.list_sessions(limit=200)
        return next((s for s in rows if s["session_id"] == sid), None)

    def set_pid(self, sid: str, pid: int | None, ppid: int | None = None) -> None:
        with self.db.tx() as conn:
            if ppid is not None:
                conn.execute("UPDATE sessions SET pid=?, ppid=? WHERE session_id=?", (pid, ppid, sid))
            else:
                conn.execute("UPDATE sessions SET pid=? WHERE session_id=?", (pid, sid))

    def get_session_pid(self, sid: str) -> int | None:
        row = self.db.one("SELECT pid FROM sessions WHERE session_id=?", (sid,))
        return int(row["pid"]) if row and row["pid"] else None

    # -- approvals ---------------------------------------------------------
    def create_approval(
        self, *, session_id: str, agent: str, metric: str | None, value: float | None,
        limit: float | None, reason: str, enforcement: str | None = None,
    ) -> dict[str, Any]:
        rid = new_id("apr")
        ts = now()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO approvals (id, session_id, agent, metric, value, limit_value, reason, "
                "status, created_ts, enforcement) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, session_id, agent, metric, value, limit, reason, "pending", ts, enforcement),
            )
        return self.get_approval(rid)  # type: ignore[return-value]

    def get_approval(self, rid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM approvals WHERE id=?", (rid,))
        if not r:
            return None
        return {
            "id": r["id"], "session_id": r["session_id"], "agent": r["agent"],
            "metric": r["metric"], "value": r["value"], "limit": r["limit_value"],
            "reason": r["reason"], "status": r["status"], "created_ts": r["created_ts"],
            "resolved_ts": r["resolved_ts"], "decision_by": r["decision_by"],
            "enforcement": r["enforcement"],
        }

    def resolve_approval(self, rid: str, decision: str, by: str = "dashboard") -> dict[str, Any] | None:
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE approvals SET status=?, resolved_ts=?, decision_by=? WHERE id=? AND status='pending'",
                (decision, now(), by, rid),
            )
        return self.get_approval(rid)

    def pending_approvals(self, sid: str | None = None) -> list[dict[str, Any]]:
        if sid:
            rows = self.db.query(
                "SELECT * FROM approvals WHERE status='pending' AND session_id=? ORDER BY created_ts DESC",
                (sid,),
            )
        else:
            rows = self.db.query("SELECT * FROM approvals WHERE status='pending' ORDER BY created_ts DESC")
        return [
            {
                "id": r["id"], "session_id": r["session_id"], "agent": r["agent"],
                "metric": r["metric"], "value": r["value"], "limit": r["limit_value"],
                "reason": r["reason"], "created_ts": r["created_ts"],
            }
            for r in rows
        ]

    # -- stats -------------------------------------------------------------
    def totals(self) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT agent, COUNT(*) events, SUM(1) as e FROM events GROUP BY agent"
        )
        return {r["agent"]: dict(r) for r in rows}
