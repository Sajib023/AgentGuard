#!/usr/bin/env python3
"""AgentGuard hooks adapter for Claude Code.

Claude Code fires lifecycle hooks as small JSON over stdin; this script maps
them onto the shared AgentGuard event schema and enforces the firewall /
circuit breaker at the two gates that matter:

  SessionStart      -> session_start (+ pid registration)
  UserPromptSubmit  -> firewall check on the prompt (block/sanitize/approve)
  PreToolUse        -> breaker shield + firewall check on tool input
  PostToolUse       -> tool_call result event
  Stop / SessionEnd -> session_end

Install (adds hooks to ~/.claude/settings.json or per-project .claude/settings.json):

  "hooks": { "SessionStart": [{"hooks": [{"type": "command", "command":
      "python3 /path/to/agentguard_hook.py"}]}, ...], ... }

See integrations/claude/settings.example.json for the full wiring.

Exit codes (Claude Code semantics):
    0            allow
    2            deny — stderr is shown to the agent as the reason

Environment:
    AGENTGUARD_URL        default http://127.0.0.1:8907
    AGENTGUARD_MODE       enforce | observe (default enforce); observe records
                          everything but never blocks
    AGENTGUARD_BREAKER    set to "0" to skip the breaker shield on tools
    AGENTGUARD_APPROVAL_TIMEOUT   seconds to approve on the dashboard (default 120)

Design note — fail-open: when the local service is unreachable, the hook
never blocks the agent (documented trade-off: availability over protection).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("AGENTGUARD_URL", "http://127.0.0.1:8907").rstrip("/")
ENFORCE = os.environ.get("AGENTGUARD_MODE", "enforce") == "enforce"
BREAKER = os.environ.get("AGENTGUARD_BREAKER", "1") != "0"
APPROVAL_TIMEOUT = int(os.environ.get("AGENTGUARD_APPROVAL_TIMEOUT", "120"))


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


def _session_id(ev: dict) -> str:
    return ev.get("session_id") or "unknown"


def _deny(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def _digest(text: str) -> str:
    import hashlib

    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{h}{len(text):x}"


def _breaker_open(sid: str) -> str | None:
    if not BREAKER:
        return None
    st = _get(f"/v1/breaker/status/{sid}")
    if st and st.get("status") in ("breached", "stopped"):
        return st["status"]
    return None


def _tool_name(tool_input: dict) -> str:
    return tool_input.get("tool_name") or tool_input.get("name") or "unknown"


def _register(sid: str) -> None:
    _post("/v1/events", {"events": [{
        "agent": "claude",
        "session_id": sid,
        "type": "session_start",
        "data": {"cwd": os.getcwd()},
    }]})
    # The hook runs as a child of the Claude Code process: ppid is a good
    # proxy for the agent's pid so the breaker can kill it if configured.
    ppid = os.getppid()
    own = os.getpid()
    if ppid != own:
        _post(f"/v1/sessions/{sid}/pid", {"pid": ppid, "ppid": None})


def on_session_start(ev: dict) -> int:
    sid = _session_id(ev)
    _register(sid)
    return 0


def on_prompt(ev: dict) -> int:
    """UserPromptSubmit: firewall the raw prompt. Signals AgentGuard:
    concurrency-safe approval pause happens on the service side."""
    sid = _session_id(ev)
    text = ev.get("prompt") or ""
    if ev.get("hook_event_name") == "UserPromptSubmit" and not text:
        # Some versions pass prompt under different keys; best effort.
        text = ev.get("user_prompt") or ev.get("input", {}).get("prompt", "")
    if not str(text).strip():
        return 0
    v = _post("/v1/firewall/check", {
        "text": str(text),
        "session_id": sid,
        "agent": "claude",
        "context_type": "prompt",
        "await_approval": True,
        "approval_timeout": APPROVAL_TIMEOUT,
    }) or {}
    action = v.get("action", "allow")
    if action == "allow":
        return 0
    if action == "sanitize":
        # Claude Code honors updatedPrompt on UserPromptSubmit; harmless if not
        print(json.dumps({"updatedPrompt": v.get("sanitized_text") or text}))
        return 0
    if not ENFORCE:
        return 0
    if action == "approve":
        return _deny(
            "agentguard: action pending manual approval in the AgentGuard "
            "dashboard (resolve it, then re-send)")
    return _deny(f"agentguard: prompt blocked by firewall — {v.get('decision_reason')}")


def on_pre_tool(ev: dict) -> int:
    sid = _session_id(ev)
    tool = _tool_name(ev)
    tool_input = ev.get("tool_input") or {}
    # Management escape hatch: anything that manages AgentGuard itself passes
    # the shield (an open circuit must not lock out the reset commands).
    try:
        serialized = json.dumps(tool_input)
    except Exception:
        serialized = ""
    mgmt = ("/v1/breaker" in serialized or "/v1/approvals" in serialized
            or "/v1/config" in serialized)
    status = _breaker_open(sid)
    if status and not mgmt:
        return _deny(
            f"agentguard: tool call blocked — circuit breaker {status} "
            "(approve/reset in AgentGuard, then continue)")
    _post("/v1/events", {"events": [{
        "agent": "claude",
        "session_id": sid,
        "type": "tool_call",
        "data": {"name": tool, "args_digest": _digest(serialized or tool),
                 "args_preview": serialized[:240], "status": "started"},
    }]})
    v = _post("/v1/firewall/check", {
        "text": serialized[:20000], "session_id": sid, "agent": "claude",
        "context_type": "tool_input",
    }) or {}
    action = v.get("action", "allow")
    if action == "sanitize" and ENFORCE:
        # best effort redaction: report; executing agents re-read input from
        # pipeline state, so we surface the redaction instead of mutating
        print(json.dumps({
            "hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "ask"},
        }))
        print(f"agentguard: redacted tool input — resubmit without secrets "
              f"({v.get('decision_reason')})", file=sys.stderr)
        return 0
    if ENFORCE and action == "block":
        return _deny(f"agentguard: tool call blocked by firewall — {v.get('decision_reason')}")
    if ENFORCE and action == "approve":
        return _deny("agentguard: pending manual approval in the AgentGuard dashboard")
    return 0


def on_post_tool(ev: dict) -> int:
    sid = _session_id(ev)
    tool = _tool_name(ev)
    tool_resp = ev.get("tool_response")
    try:
        resp = json.dumps(tool_resp)
    except TypeError:
        resp = str(tool_resp or "")
    err = ev.get("error") or ""
    _post("/v1/events", {"events": [{
        "agent": "claude",
        "session_id": sid,
        "type": "tool_call",
        "data": {"name": tool,
                 "status": "error" if err else "success",
                 "result_preview": str(resp or err)[:240]},
    }]})
    return 0


def on_stop(ev: dict) -> int:
    sid = _session_id(ev)
    _post("/v1/events", {"events": [{
        "agent": "claude", "session_id": sid, "type": "session_end", "data": {},
    }]})
    return 0


HANDLERS = {
    "SessionStart": on_session_start,
    "UserPromptSubmit": on_prompt,
    "PreToolUse": on_pre_tool,
    "PostToolUse": on_post_tool,
    "Stop": on_stop,
    "SessionEnd": on_stop,
}


def main() -> int:
    try:
        raw = sys.stdin.read()
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # malformed hook payload: never break the agent
    handler = HANDLERS.get(ev.get("hook_event_name") or "")
    if handler is None:
        return 0
    try:
        return handler(ev)
    except Exception:
        return 0  # fail-open


if __name__ == "__main__":
    sys.exit(main())
