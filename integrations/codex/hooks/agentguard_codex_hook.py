#!/usr/bin/env python3
"""AgentGuard lifecycle-hook adapter for Codex CLI.

Codex ships a hooks framework (config: ~/.codex/hooks.json; see the Codex
"Hooks" guide). This script implements the full enforcement surface Codex
supports:

  SessionStart       -> session_start event + agent pid registration
  UserPromptSubmit   -> firewall check; block (no prompt rewrite in Codex)
  PreToolUse         -> breaker shield + firewall; deny OR rewrite tool input
  PostToolUse        -> tool_call result event
  SubagentStart/Stop -> state_change events (multi-agent visibility)
  Interrupt          -> state_change event
  Stop               -> turn recorded; NEVER continues the turn
  SessionEnd         -> session_end event

Installed via integrations/codex/install.sh, which wires ~/.codex/hooks.json.
After installing, run /hooks inside Codex to review + TRUST the hooks (Codex
skips untrusted hooks), or start once with --dangerously-bypass-hook-trust.

Output contract notes (from the Codex hooks guide):
  * hook blocks via exit code 2 + stderr, or JSON
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
     "permissionDecision": "deny", "permissionDecisionReason": "..."}}.
  * PreToolUse rewrites via permissionDecision "allow" + "updatedInput".
  * Stop with {"decision": "block"} CONTINUES the turn — this adapter must
    never emit that, or sessions would never end.
  * Prompt rewrite is not supported for UserPromptSubmit: firewall
    `sanitize` (secrets) blocks the prompt instead — same guarantee as the
    other agents' rewrite (no secrets reach the model), expressed as deny.

Environment:
    AGENTGUARD_URL   default http://127.0.0.1:8907
    AGENTGUARD_MODE  enforce | observe (default enforce)
    AGENTGUARD_BREAKER  "0" disables the breaker shield
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
            if any(term in name for term in ("codex", "python", "node")):
                return parent.pid
    except Exception:
        pass
    return ppid


def _out(obj: dict) -> None:
    print(json.dumps(obj))


def _deny_tool(reason: str) -> None:
    _out({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def _deny_prompt(reason: str) -> None:
    _out({"decision": "block", "reason": reason})


def _deny_permission(message: str) -> None:
    _out({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": message},
        }
    })


def _post(path: str, payload: dict) -> dict | None:
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


def _register(sid: str, ev: dict) -> None:
    _post("/v1/events", {"events": [{
        "agent": "codex",
        "session_id": sid,
        "type": "session_start",
        "data": {"cwd": ev.get("cwd") or os.getcwd(),
                 "model": ev.get("model") or None},
    }]})
    ppid = _detect_agent_pid()
    own = os.getpid()
    if ppid and ppid != own:
        _post(f"/v1/sessions/{sid}/pid", {"pid": ppid, "ppid": None})


def _breaker_open(sid: str) -> str | None:
    if not BREAKER:
        return None
    st = _get(f"/v1/breaker/status/{sid}")
    if st and st.get("status") in ("breached", "stopped"):
        return st["status"]
    return None


def _digest(text: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{h}{len(text):x}"


def is_mgmt(text: str) -> bool:
    return "/v1/breaker" in text or "/v1/approvals" in text or "/v1/config" in text


# --------------------------------------------------------------- handlers --
def on_session_start(ev: dict) -> int:
    _register(ev.get("session_id") or "unknown", ev)
    return 0


def on_prompt(ev: dict) -> int:
    sid = ev.get("session_id") or "unknown"
    text = ev.get("prompt") or ""
    if not str(text).strip():
        return 0
    v = _post("/v1/firewall/check", {
        "text": str(text),
        "session_id": sid,
        "agent": "codex",
        "direction": "inbound",
        "context_type": "prompt",
    }) or {}
    action = v.get("action", "allow")
    if not ENFORCE:
        return 0
    if action == "block":
        _deny_prompt(f"agentguard: prompt blocked by firewall — {v.get('decision_reason')}")
        return 0
    if action == "approve":
        _deny_prompt("agentguard: review pending in the AgentGuard dashboard "
                     "(resolve it, then resend)")
        return 0
    if action == "sanitize" and v.get("redaction_count", 0) > 0:
        # Codex hooks cannot rewrite prompts; deny with the same guarantee
        # other adapters deliver via rewrite: no secrets reach the model.
        _deny_prompt(
            f"agentguard: {v['redaction_count']} secret(s) in prompt — "
            "Codex prompts cannot be rewritten in place; remove them and resend")
        return 0
    # remaining sanitize kinds (e.g. encoded payload): warn without blocking
    if action == "sanitize":
        _out({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": f"agentguard: flagged by firewall — {v.get('decision_reason')}",
            }
        })
    return 0


def on_pre_tool(ev: dict) -> int:
    sid = ev.get("session_id") or "unknown"
    tool = ev.get("tool_name") or "unknown"
    tool_input = ev.get("tool_input") or {}
    try:
        serialized = json.dumps(tool_input)
    except Exception:
        serialized = ""

    # ESCAPE HATCH: managing AgentGuard itself passes the breaker shield —
    # an open circuit must never block the commands that reset it.
    if not is_mgmt(serialized):
        status = _breaker_open(sid)
        if status:
            _deny_tool(f"agentguard: tool call blocked — circuit breaker {status} "
                       "(approve/reset in AgentGuard)")
            return 0
    _post("/v1/events", {"events": [{
        "agent": "codex",
        "session_id": sid,
        "type": "tool_call",
        "data": {"name": tool, "args_digest": _digest(serialized or tool),
                 "args_preview": serialized[:240], "status": "started"},
    }]})

    v = _post("/v1/firewall/check", {
        "text": serialized[:20000],
        "session_id": sid,
        "agent": "codex",
        "direction": "inbound",
        "context_type": "tool_input",
    }) or {}
    action = v.get("action", "allow")
    if not ENFORCE:
        return 0
    if action == "block":
        _deny_tool(f"agentguard: tool call blocked by firewall — {v.get('decision_reason')}")
        return 0
    if action == "approve":
        _deny_tool("agentguard: review pending in the AgentGuard dashboard")
        return 0
    if action == "sanitize":
        try:
            sanitized = json.loads(v.get("sanitized_text") or serialized)
        except Exception:
            sanitized = None
        if sanitized is None:
            _deny_tool("agentguard: tool input needs redaction, could not rewrite")
            return 0
        _out({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": sanitized,
            }
        })
    return 0


def on_post_tool(ev: dict) -> int:
    sid = ev.get("session_id") or "unknown"
    tool = ev.get("tool_name") or "unknown"
    resp = ev.get("tool_response")
    try:
        resp_text = json.dumps(resp)
    except TypeError:
        resp_text = str(resp or "")
    failed = ev.get("error") or (isinstance(resp, dict) and resp.get("is_error"))
    _post("/v1/events", {"events": [{
        "agent": "codex",
        "session_id": sid,
        "type": "tool_call",
        "data": {"name": tool,
                 "status": "error" if failed else "success",
                 "result_preview": str(resp_text or ev.get("error") or "")[:240]},
    }]})
    return 0


def on_state(ev: dict, state: str) -> int:
    sid = ev.get("session_id") or "unknown"
    data: dict = {"state": state}
    for key in ("turn_id", "agent_id", "agent_type", "source", "reason"):
        if ev.get(key) is not None:
            data[key] = ev[key]
    _post("/v1/events", {"events": [{
        "agent": "codex", "session_id": sid, "type": "state_change", "data": data,
    }]})
    return 0


def on_turn_stop(ev: dict) -> int:
    # NOTE: do NOT emit {"decision": "block"} here — for Codex Stop that
    # forces ANOTHER model turn. This hook only records telemetry.
    return on_state(ev, "turn_stop")


def on_session_end(ev: dict) -> int:
    sid = ev.get("session_id") or "unknown"
    _post("/v1/events", {"events": [{
        "agent": "codex", "session_id": sid, "type": "session_end", "data": {},
    }]})
    return 0


def on_permission(ev: dict) -> int:
    """PermissionRequest: Codex is about to ask the USER for approval.

    Deliberately declines to auto-allow (that would silently bypass the
    user's approval prompts) and deliberately skips the firewall — PreToolUse
    already ran it for this call; re-running here would double-count tool
    calls and LLM-guard invocations. Only an open breaker denies explicitly.
    """
    sid = ev.get("session_id") or "unknown"
    tool_input = ev.get("tool_input") or {}
    try:
        serialized = json.dumps(tool_input)
    except Exception:
        serialized = ""
    if is_mgmt(serialized):
        return 0
    status = _breaker_open(sid)
    if status:
        _deny_permission(
            f"agentguard: circuit breaker {status} — approve/reset in AgentGuard")
    return 0


HANDLERS = {
    "SessionStart": on_session_start,
    "SessionEnd": on_session_end,
    "UserPromptSubmit": on_prompt,
    "PreToolUse": on_pre_tool,
    "PermissionRequest": on_permission,
    "PostToolUse": on_post_tool,
    "SubagentStart": lambda ev: on_state(ev, "subagent_start"),
    "SubagentStop": lambda ev: on_state(ev, "subagent_stop"),
    "Interrupt": lambda ev: on_state(ev, "interrupted"),
    "Stop": on_turn_stop,
}


def main() -> int:
    try:
        raw = sys.stdin.read()
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # malformed payload: never break the agent
    handler = HANDLERS.get(ev.get("hook_event_name") or "")
    if handler is None:
        return 0
    try:
        return handler(ev)
    except Exception:
        return 0  # fail-open


if __name__ == "__main__":
    sys.exit(main())
