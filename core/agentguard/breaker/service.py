"""Loop detection + budget enforcement (the circuit breaker core).

Uses observable execution patterns only: tool-call signatures, event timing,
token counters. Never inspects hidden model reasoning.
"""

from __future__ import annotations

import collections
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import oscompat
from ..config import BreakerConfig, BreakerDefaults
from ..schema import AgentKind, Event, EventType
from ..utils import new_id, now, sha256_text


@dataclass
class SessionBreakerState:
    session_id: str
    agent: str
    started_ts: float
    limits: dict[str, float]
    recent_sigs: collections.deque = field(default_factory=lambda: collections.deque(maxlen=24))
    last_activity: float = 0.0
    last_iteration: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    consecutive_tool_errors: int = 0
    last_alert_ts: dict[str, float] = field(default_factory=dict)
    status: str = "healthy"  # healthy | warning | breached | stopped

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent": self.agent,
            "status": self.status,
            "usage": {
                "iterations": self.last_iteration,
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 6),
                "wall_seconds": round(now() - self.started_ts, 1),
                "consecutive_tool_errors": self.consecutive_tool_errors,
            },
            "limits": self.limits,
            "started_ts": self.started_ts,
        }


class CircuitBreaker:
    """One instance per service; state per session."""

    def __init__(self, config: BreakerConfig, store, bus):
        self.config = config
        self.store = store
        self.bus = bus
        self.sessions: dict[str, SessionBreakerState] = {}
        self._pending: dict[str, list[dict[str, Any]]] = {}
        self.alert_hook: Callable[[str, str], None] | None = None  # extensible alarms
        # Per-session runtime limit overrides, persisted so they survive
        # resets (and service restarts). Without this, an operator reset
        # would quietly restore default budgets and instantly re-breach a
        # legitimately long-running session.
        self._overrides: dict[str, dict[str, float]] = self._load_overrides()

    # -- lifecycle ----------------------------------------------------------
    _OVERRIDES_KEY = "breaker_session_overrides"

    def _load_overrides(self) -> dict[str, dict[str, float]]:
        try:
            raw = self.store.kv_get(self._OVERRIDES_KEY) if self.store else None
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def _save_overrides(self) -> None:
        if self.store is not None:
            self.store.kv_set(self._OVERRIDES_KEY, json.dumps(self._overrides))

    def _overrides_for(self, session_id: str) -> dict[str, float]:
        return self._overrides.get(session_id) or {}

    def set_session_limits(self, session_id: str, limits: dict[str, Any]) -> dict[str, float]:
        """Runtime per-session limit overrides; persisted across resets/restarts."""
        allowed = set(self.limits_for(None))
        clean = {k: v for k, v in (limits or {}).items() if k in allowed}
        merged = {**self._overrides_for(session_id), **{k: float(v) for k, v in clean.items()}}
        self._overrides[session_id] = merged
        self._save_overrides()
        st = self.sessions.get(session_id)
        if st is not None:
            st.limits = {**st.limits, **merged}
        return st.limits if st is not None else dict(merged)

    def limits_for(self, agent: str | None) -> dict[str, float]:
        d = self.config.defaults
        overrides = self.config.agent_overrides.get(agent or "", {}) if agent else {}
        merged = {k: getattr(d, k) for k in type(d).model_fields}
        merged.update(overrides)
        return merged

    def ensure_session(self, event: Event) -> SessionBreakerState | None:
        limits = self.limits_for(event.agent.value)
        limits = {**limits, **self._overrides_for(event.session_id)}
        st = self.sessions.get(event.session_id)
        if st is None:
            st = SessionBreakerState(
                session_id=event.session_id,
                agent=event.agent.value,
                started_ts=event.ts,
                limits=limits,
            )
            self.sessions[event.session_id] = st
        # NOTE: per-session overrides (REST /v1/breaker/limits) must survive;
        # agent-level config changes apply to NEW sessions only.
        st.last_activity = event.ts
        if st.status in ("stopped",):
            st.status = "healthy"  # restart on new session activity beyond stop
        return st

    def reset(self, session_id: str) -> None:
        """Clear usage counters and any breach for a session, but KEEP its
        limits (including persisted runtime overrides). Resetting used to
        drop the whole state, which silently restored default budgets — an
        open circuit then re-tripped instantly and locked the operator out."""
        self._pending.pop(session_id, None)
        st = self.sessions.get(session_id)
        if st is None:
            return  # no live state: nothing to clear; next event re-creates it
        st.last_activity = now()
        st.started_ts = now()
        st.last_iteration = 0
        st.llm_calls = 0
        st.tool_calls = 0
        st.input_tokens = 0
        st.output_tokens = 0
        st.cost_usd = 0.0
        st.consecutive_tool_errors = 0
        st.recent_sigs.clear()
        st.last_alert_ts.clear()
        st.limits = {**st.limits, **self._overrides_for(session_id)}
        st.status = "healthy"

    def status_for(self, session_id: str) -> dict[str, Any] | None:
        st = self.sessions.get(session_id)
        if not st:
            existing = self.store.get_session(session_id) if self.store else None
            if not existing:
                return None
            limits = self.limits_for(existing["agent"])
            limits = {**limits, **self._overrides_for(session_id)}
            st = SessionBreakerState(
                session_id=session_id, agent=existing["agent"], started_ts=existing["first_ts"],
                limits=limits,
            )
            self.sessions[session_id] = st
        return st.snapshot()

    # -- main entry ---------------------------------------------------------
    def observe_event(self, event: Event) -> list[Event]:
        """Consume an event, update state, and return derived events (alerts/stops).

        Returns a list so callers can persist+broadcast derived events too.
        """
        if not self.config.enabled:
            return []
        stage = event.type
        if stage is EventType.session_start:
            self.reset(event.session_id)
        derived: list[Event] = []
        if stage is EventType.session_end:
            # expire any unresolved approvals from this session
            for req in self._pending.pop(event.session_id, []):
                self.store.resolve_approval(req["id"], "expired")
            return derived
        st = self.ensure_session(event)
        if st is None:
            return derived

        data = event.data or {}
        if stage is EventType.tool_call:
            digest = data.get("args_digest") or sha256_text(
                (data.get("args_preview") or data.get("name", "")) )
            sig = f"{data.get('name')}:{digest[:16]}"
            st.recent_sigs.append(sig)
            st.tool_calls += 1
            if data.get("status") == "error":
                st.consecutive_tool_errors += 1
            else:
                st.consecutive_tool_errors = 0
            loop_ev = self._check_loop(st)
            if loop_ev:
                derived.append(loop_ev)
            if st.limits.get("max_consecutive_tool_errors") and \
                    st.consecutive_tool_errors >= st.limits["max_consecutive_tool_errors"]:
                derived.append(self._guard(st, "tool_errors", float(st.consecutive_tool_errors),
                                           float(st.limits["max_consecutive_tool_errors"])))
        elif stage is EventType.llm_call:
            st.llm_calls += 1
            st.input_tokens += int(data.get("input_tokens") or 0)
            st.output_tokens += int(data.get("output_tokens") or 0)
            if data.get("cost_usd") is not None:
                st.cost_usd += float(data["cost_usd"])
            if data.get("iteration") is not None:
                st.last_iteration = max(st.last_iteration, int(data["iteration"]))
        elif stage is EventType.graph_event:
            if data.get("iteration") is not None:
                st.last_iteration = max(st.last_iteration, int(data["iteration"]))

        # budgets that apply after every activity event
        derived.extend(self._check_budgets(st))
        return derived

    # -- detectors ----------------------------------------------------------
    def _check_loop(self, st: SessionBreakerState) -> Event | None:
        sigs = list(st.recent_sigs)
        window = int(st.limits.get("loop_window", 12))
        repeats = int(st.limits.get("loop_repeats", 3))
        if len(sigs) < repeats:
            return None
        tail = sigs[-window:]
        # consecutive identical signature → likely stuck on a retry
        if len(sigs) >= repeats and len(set(sigs[-repeats:])) == 1:
            return self._guard(
                st, "loop", float(repeats), float(repeats),
                message=f"tool call repeated {repeats}x consecutively: {sigs[-1]}",
            )
        # periodic k-cycle (up to length 4): e.g. A B A B A B
        for k in (4, 3, 2):
            if len(tail) >= k * repeats and tail[-k:] == tail[-2 * k:-k] == tail[-3 * k:-2 * k]:
                return self._guard(
                    st, "loop", float(k * repeats), float(k * repeats),
                    message=f"cyclic pattern of {k} tool calls repeated {repeats}x: {tail[-k:]}",
                )
        # entropy-drop guard: same signatures dominate the whole window
        if len(tail) >= window and len(set(tail)) <= max(1, window // 4):
            return self._guard(
                st, "loop", float(len(tail)), float(window),
                message=f"tool diversity collapsed: {len(set(tail))} unique in {len(tail)} calls",
            )
        return None

    def _check_budgets(self, st: SessionBreakerState) -> list[Event]:
        derived: list[Event] = []
        pairs = (
            ("iterations", st.last_iteration, st.limits.get("max_iterations")),
            ("tool_calls", st.tool_calls, st.limits.get("max_tool_calls")),
            ("tokens", st.input_tokens + st.output_tokens, st.limits.get("max_tokens")),
            ("cost_usd", st.cost_usd, st.limits.get("max_cost_usd")),
            ("wall_time", now() - st.started_ts, st.limits.get("max_wall_seconds")),
        )
        warn_frac = self.config.warn_fraction
        for metric, value, limit in pairs:
            if not limit or limit <= 0:
                continue
            frac = value / limit
            if frac >= 1.0:
                ev = self._guard(st, metric, float(value), float(limit), severity="critical")
                if ev is not None:
                    derived.append(ev)
            elif frac >= warn_frac:
                ev = self._alert_once(st, metric, float(value), float(limit),
                                      message=f"{metric} at {frac:.0%} of budget")
                if ev is not None:
                    derived.append(ev)
        return derived

    # -- enforcement --------------------------------------------------------
    def _throttle_ok(self, st: SessionBreakerState, metric: str) -> bool:
        last = st.last_alert_ts.get(metric, 0.0)
        return last == 0.0 or now() - last > 5.0

    def _guard(self, st: SessionBreakerState, metric: str, value: float, limit: float,
               severity: str = "critical", message: str = "") -> Event:
        """Breach handler: alert + enforcement per config."""
        if self._throttle_ok(st, metric):
            st.last_alert_ts[metric] = now()
        st.status = "breached" if severity == "critical" else "warning"
        enforcement = self.config.on_breach
        message = message or f"{metric} {value:.2f} exceeded limit {limit:.2f}"
        result = "not_enforced"
        if enforcement == "kill":
            result = self._kill(st)
        elif enforcement == "pause":
            req = self._require_approval(st, metric, value, limit, message)
            result = "paused" if req else "not_enforced"
        else:  # alert
            result = "notified"
        st.status = "stopped" if enforcement == "kill" and result == "stopped" else st.status
        return Event(
            agent=AgentKind(st.agent),
            session_id=st.session_id,
            type=EventType.breaker_stop,
            data={
                "metric": metric, "value": value, "limit": limit,
                "severity": severity, "message": message,
                "enforcement": enforcement, "result": result,
            },
        )

    def _alert_once(self, st: SessionBreakerState, metric: str, value: float, limit: float,
                    message: str) -> Event | None:
        if not self._throttle_ok(st, f"warn_{metric}"):
            return None
        st.last_alert_ts[f"warn_{metric}"] = now()
        if st.status == "healthy":
            st.status = "warning"
        if self.alert_hook is not None:
            try:
                self.alert_hook(st.session_id, message)
            except Exception:
                pass
        return Event(
            agent=AgentKind(st.agent),
            session_id=st.session_id,
            type=EventType.breaker_alert,
            data={
                "metric": metric, "value": value, "limit": limit,
                "severity": "warning", "message": message,
            },
        )

    def _require_approval(self, st: SessionBreakerState, metric: str, value: float,
                          limit: float, message: str) -> dict[str, Any] | None:
        pending = self._pending.setdefault(st.session_id, [])
        if pending:
            return pending[0]
        if self.store is None:
            return None
        req = self.store.create_approval(
            session_id=st.session_id, agent=st.agent, metric=metric,
            value=value, limit=limit, reason=message, enforcement="pause",
        )
        pending.append(req)
        self.bus.broadcast_breaker({"kind": "approval_required", "approval": req})
        return req

    def _kill(self, st: SessionBreakerState) -> str:
        pid = self.store.get_session_pid(st.session_id) if self.store else None
        me = os.getpid()
        if not pid or pid == me or pid == os.getppid():
            return "refused_not_agent_pid"
        # never take down the service itself (or whatever launched it)
        if pid in oscompat.ancestor_pids(me):
            return "refused_ancestor"
        if not oscompat.IS_WINDOWS:
            try:
                # Prefer the process-group of the recorded agent CLI
                if os.getpgid(pid) == os.getpgrp():
                    return "refused_same_group"
            except (PermissionError, ProcessLookupError):
                pass
            except OSError:
                return "failed"
        if not oscompat.is_pid_alive(pid):
            return "failed"
        # POSIX: SIGTERM to the agent's process group; Windows: taskkill /T /F
        return "stopped" if oscompat.terminate(pid, tree=True) else "failed"
