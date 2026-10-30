#!/usr/bin/env python3
"""AgentGuard hooks adapter for Google Antigravity (App / CLI / IDE).

Antigravity fires lifecycle hooks as JSON over stdin and reads a JSON decision
from stdout; this script forwards them to the AgentGuard core service
(http://127.0.0.1:8907) and enforces the firewall / circuit breaker at the
gates Antigravity exposes:

    SessionStart   -> session_start (+ pid registration, model/workspace data)
    PreToolUse     -> breaker shield + firewall check on tool args, answered
                      with Antigravity's decision contract
                      (allow / ask / force_ask / deny, optional `overwrite`)
    PostToolUse    -> tool_call result event
    PreInvocation  -> llm_call telemetry (iteration budgeting); optional
                      prompt check when the payload carries prompt text
    PostInvocation -> no-op (present for completeness)
    Stop           -> session_end

Wiring (hooks.json — global ~/.gemini/config/hooks.json or per-workspace
.agents/hooks.json; see ../hooks.json.example):

    {"agentguard": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command",
        "command": "python3 /path/to/agentguard_antigravity_hook.py PreToolUse", "timeout": 35}]}], ...}}

The event name is passed as argv[1]: Antigravity payloads do not carry an
event discriminator (common fields overlap across events), so the installer
injects it per event. When argv[1] is absent the script falls back to payload
shape sniffing.

Decision mapping (AgentGuard verdict -> Antigravity decision):
    allow    -> {"decision": "allow"}
    sanitize -> {"decision": "allow", "overwrite": <redacted args>}  (real
                argument rewrite, unlike the Claude Code adapter's prompt
                resubmit fallback); falls back to force_ask when the redacted
                text no longer parses back into JSON
    block    -> {"decision": "deny",   "reason": ...}
    approve  -> {"decision": "force_ask", "reason": "pending manual approval
                in the AgentGuard dashboard (resolve it, then retry)"}

Environment:
    AGENTGUARD_URL        default http://127.0.0.1:8907
    AGENTGUARD_MODE       enforce | observe (default enforce); observe records
                          everything but never blocks
    AGENTGUARD_BREAKER    set to "0" to skip the breaker shield on tools

Design note — fail-open: when the local service is unreachable the hook always
allows. Antigravity hook timeouts (default 30 s) are honored from hooks.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("AGENTGUARD_URL", "http://127.0.0.1:8907").rstrip("/")
ENFORCE = os.environ.get("AGENTGUARD_MODE", "enforce") == "enforce"
BREAKER = os.environ.get("AGENTGUARD_BREAKER", "1") != "0"

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _detect_agent_pid() -> int:
    ppid = os.getppid()
    if sys.platform != "win32":
        return ppid
    try:
        import psutil  # type: ignore

        proc = psutil.Process(os.getpid())
        for parent in proc.parents():
            name = parent.name().lower()
            if any(term in name for term in ("antigravity", "node", "python", "ag")):
                return parent.pid
    except Exception:
        pass
    return ppid


def _post(path: str, payload: dict) -> dict | None:
    """Fail-open HTTP POST helper."""
    try:
        req = urllib.request.Request(
            URL + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _get(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(URL + path, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _digest(text: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{h}{len(text):x}"


def _session_id(ev: dict) -> str:
    return (ev.get("conversationId")
            or ev.get("conversation_id")
            or ev.get("sessionId")
            or "antigravity-unknown")


def _register(ev: dict) -> None:
    sid = _session_id(ev)
    workspaces = ev.get("workspacePaths") or []
    _post("/v1/events", {"events": [{
        "agent": "antigravity",
        "session_id": sid,
        "type": "session_start",
        "data": {
            "cwd": str(workspaces[0]) if workspaces else os.getcwd(),
            "model": ev.get("modelName") or os.environ.get("AGENTGUARD_MODEL"),
            "pid": _detect_agent_pid() or None,
        },
    }]})


def on_session_start(ev: dict) -> None:
    _register(ev)
    print(json.dumps({}))  # hooks may optionally injectSteps; none needed


def _breaker_open(sid: str) -> str | None:
    if not BREAKER:
        return None
    st = _get(f"/v1/breaker/status/{sid}")
    if st and st.get("status") in ("breached", "stopped"):
        return st["status"]
    return None


def _emit_tool_event(sid: str, tool: str, data: dict) -> None:
    _post("/v1/events", {"events": [{
        "agent": "antigravity", "session_id": sid, "type": "tool_call",
        "data": {"name": tool, **data},
    }]})


def on_pre_tool(ev: dict) -> None:
    sid = _session_id(ev)
    call = ev.get("toolCall") or {}
    tool = call.get("name") or "unknown"
    args = call.get("args") or {}
    try:
        serialized = json.dumps(args)
    except Exception:
        serialized = str(args)
        args = {"_unserializable": serialized}

    # Management escape hatch: AgentGuard self-management must stay possible
    # even while an open circuit would otherwise lock the tool gate.
    mgmt = ("/v1/breaker" in serialized or "/v1/approvals" in serialized
            or "/v1/config" in serialized)

    status = _breaker_open(sid)
    if status and not mgmt:
        print(json.dumps({
            "decision": "deny",
            "reason": (f"agentguard: tool call blocked — circuit breaker {status} "
                       "(approve/reset in AgentGuard, then continue)"),
        }))
        return

    _emit_tool_event(sid, tool, {
        "args_digest": _digest(serialized),
        "args_preview": serialized[:240],
        "status": "started",
    })

    v = _post("/v1/firewall/check", {
        "text": serialized[:20000],
        "session_id": sid,
        "agent": "antigravity",
        "context_type": "tool_input",
    }) or {}
    action = v.get("action", "allow")

    if action == "allow":
        print(json.dumps({"decision": "allow"}))
        return

    if action == "sanitize":
        # Map the redacted text back into Antigravity's `overwrite` arg merge.
        redacted = v.get("sanitized_text") or ""
        parsed = None
        try:
            parsed = json.loads(redacted)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and parsed != args:
            print(json.dumps({"decision": "allow", "overwrite": parsed}))
        elif not ENFORCE:
            print(json.dumps({"decision": "allow"}))
        else:
            # Redaction detected but not round-trippable: always surface it.
            print(json.dumps({
                "decision": "force_ask",
                "reason": ("agentguard: tool args contain secret material "
                           f"({v.get('redaction_count')} redaction(s)); "
                           "resubmit without secrets"),
            }))
        return

    if not ENFORCE:
        print(json.dumps({"decision": "allow"}))
        return
    if action == "approve":
        print(json.dumps({
            "decision": "force_ask",
            "reason": ("agentguard: pending manual approval in the AgentGuard "
                       "dashboard (resolve it, then retry)"),
        }))
        return
    print(json.dumps({
        "decision": "deny",
        "reason": f"agentguard: tool call blocked by firewall — {v.get('decision_reason')}",
    }))


def on_post_tool(ev: dict) -> None:
    sid = _session_id(ev)
    call = ev.get("toolCall") or {}
    err = ev.get("error") or ""
    result = ev.get("result")
    try:
        preview = json.dumps(result if result is not None else "")
    except Exception:
        preview = str(result or "")
    _emit_tool_event(sid, call.get("name") or "unknown", {
        "status": "error" if err else "success",
        "result_preview": (err and f"error: {err}") or preview,
    })
    print(json.dumps({}))


def on_pre_invocation(ev: dict) -> None:
    sid = _session_id(ev)
    model = ev.get("modelName")
    data = {"iteration": ev.get("invocationNum")}
    if model:
        data["model"] = model
    _post("/v1/events", {"events": [{
        "agent": "antigravity", "session_id": sid, "type": "llm_call",
        "data": data,
    }]})
    # Prompt-level gating is coarse here: Antigravity's PreInvocation payload
    # does not expose the prompt text. If a future revision adds prompt fields,
    # fire a firewall check on them defensively.
    prompt = ev.get("prompt") or ev.get("userPrompt")
    if isinstance(prompt, str) and prompt.strip():
        _post("/v1/firewall/check", {
            "text": prompt, "session_id": sid, "agent": "antigravity",
            "context_type": "prompt",
        })
    print(json.dumps({}))


def on_post_invocation(ev: dict) -> None:
    print(json.dumps({}))


def on_stop(ev: dict) -> None:
    _post("/v1/events", {"events": [{
        "agent": "antigravity", "session_id": _session_id(ev),
        "type": "session_end", "data": {
            "reason": ev.get("terminationReason") or "",
        },
    }]})
    print(json.dumps({}))  # never decision:"continue" — avoid self-inflicted loops


HANDLERS = {
    "SessionStart": on_session_start,
    "PreToolUse": on_pre_tool,
    "PostToolUse": on_post_tool,
    "PreInvocation": on_pre_invocation,
    "PostInvocation": on_post_invocation,
    "Stop": on_stop,
}


def _sniff(ev: dict) -> str:
    """Fallback when argv[1] is missing: infer the event from payload shape."""
    if ev.get("toolCall"):
        return "PostToolUse" if ev.get("error") is not None and "error" in ev else "PreToolUse"
    if "invocationNum" in ev:
        return "PreInvocation"
    if "terminationReason" in ev or "fullyIdle" in ev:
        return "Stop"
    return "SessionStart"


def main() -> int:
    try:
        raw = sys.stdin.read()
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # malformed hook payload: never break the agent
    name = (sys.argv[1] if len(sys.argv) > 1 else None) or _sniff(ev)
    handler = HANDLERS.get(name)
    if handler is None:
        return 0
    try:
        handler(ev)
    except Exception:
        try:
            print(json.dumps({"decision": "allow"}))
        except Exception:
            pass
    return 0  # Antigravity semantics: stdout decision governs; never fail the agent


if __name__ == "__main__":
    sys.exit(main())
