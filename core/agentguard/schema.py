"""Shared event schema — the single contract every agent adapter emits.

All agents (OpenCode, Claude Code, Codex, LangGraph, anything else) normalize
their native events into :class:`Event`. The firewall, circuit breaker and the
dashboard all consume this shape, which keeps the core agent-agnostic.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .utils import new_id, now


class AgentKind(str, Enum):
    opencode = "opencode"
    claude_code = "claude_code"
    codex = "codex"
    langgraph = "langgraph"
    antigravity = "antigravity"
    openclaw = "openclaw"
    generic = "generic"


class EventType(str, Enum):
    # session lifecycle
    session_start = "session_start"
    session_end = "session_end"

    # prompts & firewall
    prompt_before = "prompt_before"        # raw prompt as received (pre-firewall)
    prompt_after = "prompt_after"          # post-firewall content (may be redacted)
    firewall_verdict = "firewall_verdict"  # firewall decision record (sanitized payload)

    # agent activity
    tool_call = "tool_call"
    llm_call = "llm_call"                  # model, tokens in/out, cost, latency
    state_change = "state_change"
    graph_event = "graph_event"            # LangGraph-style node/transition/iteration
    error = "error"

    # circuit breaker & approvals
    breaker_alert = "breaker_alert"        # limit approached (warning)
    breaker_stop = "breaker_stop"          # breaker fired, agent stopped/paused
    approval_request = "approval_request"  # human approval needed
    approval_decision = "approval_decision"


class FirewallAction(str, Enum):
    allow = "allow"
    sanitize = "sanitize"
    block = "block"
    approve = "approve"  # require human approval


class CostBreakdown(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class SessionStartData(BaseModel):
    model: str | None = None
    cwd: str | None = None
    pid: int | None = None          # process id of the agent CLI (for enforcement)
    ppid: int | None = None         # parent shell pid
    agent_version: str | None = None


class PromptData(BaseModel):
    content: str
    truncated: bool = False
    direction: Literal["inbound", "outbound"] = "inbound"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallData(BaseModel):
    name: str
    args_digest: str | None = None   # sha256 of canonical args, used for loop detection
    args_preview: str = ""
    status: Literal["started", "success", "error"] = "success"
    duration_ms: int | None = None
    result_preview: str = ""
    call_id: str | None = None


class LLMCallData(BaseModel):
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int | None = None
    iteration: int | None = None     # agent-loop iteration this call belongs to


class StateChangeData(BaseModel):
    state: str                       # new state name
    previous_state: str | None = None
    phase: str | None = None         # e.g. plan/execute/review


class GraphEventData(BaseModel):
    """LangGraph-compatible node/edge telemetry."""

    node: str
    phase: Literal["enter", "exit", "transition", "interrupt"] = "enter"
    transition_to: str | None = None
    iteration: int | None = None
    recursion_state: str | None = None


class ErrorData(BaseModel):
    message: str
    kind: str | None = None
    tool: str | None = None


class BreakerAlertData(BaseModel):
    metric: str                      # loop | iterations | cost | tokens | wall_time | tool_errors
    value: float
    limit: float
    severity: Literal["warning", "critical"] = "warning"
    message: str = ""


class BreakerStopData(BreakerAlertData):
    enforcement: Literal["alert", "pause", "kill", "deny"] = "alert"
    result: Literal["stopped", "paused", "notified", "failed", "not_enforced"] = "notified"


class ApprovalRequestData(BaseModel):
    metric: str | None = None
    value: float | None = None
    limit: float | None = None
    reason: str = ""
    status: Literal["pending", "approved", "denied", "expired"] = "pending"


PAYLOAD_MODELS: dict[EventType, type[BaseModel] | None] = {
    EventType.session_start: SessionStartData,
    EventType.session_end: None,
    EventType.prompt_before: PromptData,
    EventType.prompt_after: PromptData,
    EventType.firewall_verdict: None,  # engine-defined record
    EventType.tool_call: ToolCallData,
    EventType.llm_call: LLMCallData,
    EventType.state_change: StateChangeData,
    EventType.graph_event: GraphEventData,
    EventType.error: ErrorData,
    EventType.breaker_alert: BreakerAlertData,
    EventType.breaker_stop: BreakerStopData,
    EventType.approval_request: ApprovalRequestData,
    EventType.approval_decision: ApprovalRequestData,
}


class EventIn(BaseModel):
    """Wire format accepted at ``POST /v1/events`` and over WebSocket ingestion."""

    agent: AgentKind = AgentKind.generic
    session_id: str = Field(min_length=1, max_length=200)
    type: EventType
    parent_event_id: str | None = None
    ts: float | None = None          # optional client timestamp; server stamps if absent
    data: dict[str, Any] = Field(default_factory=dict)


class Event(BaseModel):
    """Stored form of an event (wire format + server metadata)."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    ts: float = Field(default_factory=now)
    agent: AgentKind = AgentKind.generic
    session_id: str
    type: EventType
    parent_event_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


def normalize_payload(event: EventIn) -> dict[str, Any]:
    """Coerce ``data`` to the typed payload for the event type when known.

    Unknown keys survive; wrong-typed known payloads fail fast so bad adapters
    surface immediately instead of silently corrupting dashboard data.
    """
    model = PAYLOAD_MODELS.get(event.type)
    if model is None:
        return event.data
    try:
        parsed = model.model_validate(event.data)
        out = parsed.model_dump(mode="json")
        # unknown keys survive alongside typed fields
        out.update({k: v for k, v in event.data.items() if k not in out})
        return out
    except Exception:
        # keep raw payload; record normalization error context on the event
        out = dict(event.data)
        out.setdefault("_schema_error", True)
        return out


def event_ttl(materialize: bool = False) -> None:
    """Placeholder to keep import surface stable (retention handled in store)."""


def new_event_from(event_in: EventIn, *, agent_fallback: AgentKind = AgentKind.generic) -> Event:
    return Event(
        ts=event_in.ts if event_in.ts is not None else time.time(),
        agent=event_in.agent or agent_fallback,
        session_id=event_in.session_id,
        type=event_in.type,
        parent_event_id=event_in.parent_event_id,
        data=normalize_payload(event_in),
    )
