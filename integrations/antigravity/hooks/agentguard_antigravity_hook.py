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
    PreInvocation  -> llm_call telemetry (iteration budgeting + token usage
                      mined from the conversation transcript delta); optional
                      prompt check when the payload carries prompt text
    PostInvocation -> no-op (present for completeness)
    Stop           -> flushes remaining transcript usage, then session_end

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

Token telemetry: Antigravity payloads carry no model usage, but usage records
land in the conversation transcript JSONL between invocations. Before each
PreInvocation / Stop the adapter reads only the region past a per-conversation
cursor (state file ~/.agentguard/hooks/.usage_state/<sha1>.json) and folds the
new records into that invocation's single llm_call event — usage of call N-1
arrives with invocation N; Stop flushes the remainder. Parsing is fail-open
and best-effort: unrecognized shapes simply emit a bare llm_call.

Design note — fail-open: when the local service is unreachable the hook always
allows. Antigravity hook timeouts (default 30 s) are honored from hooks.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

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


DEBUG_LOG = os.environ.get("AGENTGUARD_HOOK_DEBUG") == "1"


def _dbg(event_name: str, fields: dict) -> None:
    """Local-only trace of what the hook saw, appended to
    ~/.agentguard/hooks/antigravity_hook_debug.log when
    AGENTGUARD_HOOK_DEBUG=1. Never enabled by default."""
    if not DEBUG_LOG:
        return
    home = os.environ.get("AGENTGUARD_HOME") or os.path.join(
        os.path.expanduser("~"), ".agentguard")
    path = Path(home) / "hooks" / "antigravity_hook_debug.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event_name, **fields}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


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
    _dbg("session_start", {"payload_keys": sorted(str(k) for k in ev.keys())[:24],
                           "transcriptPath": ev.get("transcriptPath"),
                           "artifactDirectoryPath": ev.get("artifactDirectoryPath")})
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


# ----------------------------------------------------------------------------
# Token usage mining from the conversation transcript. Hook payloads expose no
# usage; model call usage lands in the transcript JSONL between invocations, so
# each PreInvocation consumes the delta since the previous scan (cursor kept in
# ~/.agentguard/hooks/.usage_state/) and Stop flushes the remainder.
# ----------------------------------------------------------------------------

INPUT_KEYS = ("promptTokenCount", "prompt_token_count", "prompt_tokens",
              "input_tokens", "inputTokens", "messages_input_tokens",
              "text_input_tokens")
OUTPUT_KEYS = ("candidatesTokenCount", "candidates_token_count",
               "completion_tokens", "output_tokens", "outputTokens")
CACHE_READ_KEYS = ("cachedContentTokenCount", "cached_tokens", "cachedTokens",
                   "cache_read_tokens", "cacheReadTokens", "cache_read_input_tokens")
CACHE_WRITE_KEYS = ("cache_creation_input_tokens", "cache_creation_tokens",
                    "cacheWriteTokens", "cache_write_tokens")
_SCAN_CAP_BYTES = 16 * 1024 * 1024  # read at most this much per invocation


def _first_int(d: dict, *keys: str) -> int | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v >= 0:
            return int(v)
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
    return None


def _cache_probe(d: dict, keys: tuple) -> int | None:
    """Cache counts sometimes nest one level under the usage dict (e.g.
    OpenAI-style prompt_tokens_details.cached_tokens)."""
    v = _first_int(d, *keys)
    if v is not None:
        return v
    for k in list(d)[:32]:
        child = d[k]
        if isinstance(child, dict):
            v = _first_int(child, *keys)
            if v is not None:
                return v
    return None


def _find_usage(node: object, depth: int = 0):
    """Bounded DFS for the first dict carrying recognizable token counts.
    Returns (record, snippet) or (None, None); snippet shows the matched
    usage dict's keys/shape for AGENTGUARD_HOOK_DEBUG=1 tracing."""
    if depth > 8 or not isinstance(node, (dict, list)):
        return None, None
    if isinstance(node, dict):
        input_ = _first_int(node, *INPUT_KEYS)
        output_ = _first_int(node, *OUTPUT_KEYS)
        if input_ is not None or output_ is not None:
            rec = {
                "input": input_ or 0,
                "output": output_ or 0,
                "cache_read": _cache_probe(node, CACHE_READ_KEYS) or 0,
                "cache_write": _cache_probe(node, CACHE_WRITE_KEYS) or 0,
            }
            try:
                snippet = json.dumps(node, default=str)[:300]
            except Exception:
                snippet = "<unserializable>"
            return rec, snippet
        children = [node[k] for k in list(node)[:64]]
    else:
        children = list(node)[:64]
    for child in children:
        rec, snippet = _find_usage(child, depth + 1)
        if rec:
            return rec, snippet
    return None, None


def _usage_state_file(path: str, sid: str) -> Path | None:
    base = os.environ.get("AGENTGUARD_HOME") or os.path.join(
        os.path.expanduser("~"), ".agentguard")
    d = Path(base) / "hooks" / ".usage_state"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None  # cursor persistence unavailable: mining would recount
    return d / (hashlib.sha1(f"{path}|{sid}".encode()).hexdigest() + ".json")


def _scan_usage_delta(ev: dict) -> dict:
    """Sum usage records appended to the transcript past the stored cursor and
    advance it (rotation/truncation resets the cursor; an unterminated trailing
    line is left for the next scan so records are consumed exactly once)."""
    out = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "found": 0,
           "snippet": None}
    dbg: dict = {}
    path = ev.get("transcriptPath") or ev.get("transcript_path")
    if not isinstance(path, str) or not path:
        _dbg("transcript_scan", {"note": "payload carries no transcript path",
                                 "payload_keys": sorted(str(k) for k in ev.keys())[:24]})
        return out
    dbg["path_raw"] = path
    path = os.path.expanduser(path)  # Antigravity sends a literal '~' prefix
    state = _usage_state_file(path, _session_id(ev))
    if state is None:
        dbg["state"] = "unavailable"
        _dbg("transcript_scan", dbg)
        return out
    offset = 0
    try:
        offset = int(json.loads(state.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        offset = 0
    dbg["offset_before"] = offset
    try:
        fsize = os.path.getsize(path)
        dbg["exists"] = True
        dbg["size"] = fsize
        if fsize < offset:
            offset = 0  # transcript rotated / truncated
            dbg["rotated"] = True
        if fsize <= offset:
            dbg["note"] = "no new bytes past cursor"
            dbg["offset_after"] = offset
            _dbg("transcript_scan", dbg)
            return out
        consumed = 0
        huge = bad = lines = 0
        with open(path, "rb") as fh:
            fh.seek(offset)
            for raw in fh:
                if consumed + len(raw) > _SCAN_CAP_BYTES:
                    dbg["note"] = "hit per-scan byte cap"
                    break  # resume from current point on the next scan
                if not raw.endswith(b"\n"):
                    dbg["note"] = "stopped at unterminated tail (transcript mid-write)"
                    break  # unterminated tail (transcript mid-write)
                consumed += len(raw)
                lines += 1
                low = raw.lower()
                if (b"usage" not in low and b"tokens" not in low
                        and b"tokencount" not in low and b"token_count" not in low):
                    continue  # cheap prefilter: line cannot carry usage
                if len(raw) > 1_000_000:
                    huge += 1
                    dbg.setdefault("huge_lines", []).append(len(raw))  # type: ignore[union-attr]
                    continue
                try:
                    rec, snippet = _find_usage(json.loads(raw))
                except Exception:
                    bad += 1
                    continue  # skip malformed / non-JSON lines
                if rec:
                    out["input"] += rec["input"]
                    out["output"] += rec["output"]
                    out["cache_read"] += rec["cache_read"]
                    out["cache_write"] += rec["cache_write"]
                    out["found"] += 1
                    if out["snippet"] is None:
                        out["snippet"] = snippet
        dbg["scanned_lines"] = lines
        dbg["scanned_bytes"] = consumed
        dbg["malformed"] = bad
        dbg["huge_skipped"] = huge
        dbg["usage_records"] = out["found"]
        dbg["offset_after"] = offset + consumed
        if consumed and dbg.get("note") != "hit per-scan byte cap":
            try:
                state.write_text(json.dumps({"offset": offset + consumed}), encoding="utf-8")
            except OSError:
                dbg["note"] = "cursor write failed"
    except OSError:
        dbg["exists"] = False
        dbg["note"] = "transcript path unreadable"
    _dbg("transcript_scan", dbg)
    return out


def _usage_event_data(usage: dict) -> dict:
    data = {
        "input_tokens": usage["input"],
        "output_tokens": usage["output"],
        "cache_read_tokens": usage["cache_read"],
    }
    if usage["cache_write"]:
        data["cache_write_tokens"] = usage["cache_write"]
    return data


def on_pre_invocation(ev: dict) -> None:
    sid = _session_id(ev)
    model = ev.get("modelName")
    data: dict = {"iteration": ev.get("invocationNum")}
    if model:
        data["model"] = model
    usage = _scan_usage_delta(ev)
    if usage["found"]:
        # Usage records from model call N-1 land between invocations; fold
        # them into this invocation's single llm_call event.
        data.update(_usage_event_data(usage))
    _dbg("pre_invocation", {
        "payload_keys": sorted(str(k) for k in ev.keys())[:24],
        "usage_found": usage["found"],
        "tokens": {k: usage[k] for k in ("input", "output", "cache_read", "cache_write")},
        "usage_shape": usage["snippet"],
        "llm_call_data": data,
    })
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
    sid = _session_id(ev)
    usage = _scan_usage_delta(ev)  # flush whatever the last invocation missed
    if usage["found"]:
        _post("/v1/events", {"events": [{
            "agent": "antigravity", "session_id": sid, "type": "llm_call",
            "data": _usage_event_data(usage),
        }]})
    _dbg("stop", {"payload_keys": sorted(str(k) for k in ev.keys())[:24],
                  "usage_found": usage["found"],
                  "tokens": {k: usage[k] for k in ("input", "output", "cache_read", "cache_write")}})
    _post("/v1/events", {"events": [{
        "agent": "antigravity", "session_id": sid,
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
