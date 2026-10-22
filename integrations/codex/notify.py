#!/usr/bin/env python3
"""AgentGuard notify adapter for Codex CLI.

The Codex CLI exposes exactly one outbound integration point: the `notify`
hook, invoked when turns complete. It has no prompt or tool interception, so
this adapter is **observability-only** by design:

  * every completed turn is streamed into the shared event schema
  * the session appears on the live dashboard with real token/cost data
    if the payload exposes it
  * the circuit breaker still sees the events → its limit/loop detectors
    stay authoritative, and `kill` works through the registered parent pid

What it deliberately does NOT do: firewall Codex prompts. Codex offers no
in-line gate; pairing it with the AgentGuard CLI (agentguard stop / /v1
breakers) gives you the enforcement surface.

Install — add to ~/.codex/config.toml:

    notify = ["python3", "/home/sajib/AgentGuard/integrations/codex/notify.py"]

Payload (stdin/argv per Codex version): JSON such as
    {"type": "agent-turn-complete", "turn-id": "...",
     "input-messages": [...], "last-assistant-message": "..."}

Environment:
    AGENTGUARD_URL   default http://127.0.0.1:8907
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("AGENTGUARD_URL", "http://127.0.0.1:8907").rstrip("/")


def _post(path: str, payload: dict) -> None:
    try:
        req = urllib.request.Request(
            URL + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        return  # fail-open: never disturb the agent


def _get(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(URL + path, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def derive_sid(payload: dict) -> str:
    # Codex payloads vary by version; prefer a real conversation/thread id.
    # A turn-id is NOT a session id (it would fragment the dashboard), so
    # when no thread/session id exists, fall back to a stable per-workspace
    # hash: one checkout == one dashboard row.
    for key in ("thread-id", "thread_id", "session_id", "conversation-id", "conversation_id"):
        if payload.get(key):
            return "codex-" + str(payload[key])[:24]
    cwd = payload.get("cwd") or os.getcwd()
    return "codex-" + hashlib.sha256(cwd.encode()).hexdigest()[:12]


def main() -> int:
    raw = ""
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    if not raw:
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not payload:
        return 0

    etype = payload.get("type") or "codex-event"
    sid = derive_sid(payload)
    events = []

    # Register the session once (notify is a distinct process each turn; the
    # repeated session_start would otherwise reset breaker counters).
    known = _get(f"/v1/sessions/{sid}") is not None
    if not known:
        events.append({"type": "session_start",
                       "data": {"cwd": payload.get("cwd") or os.getcwd()}})
        # notify is a child of the codex process → record that pid for kill
        ppid = os.getppid()
        _post(f"/v1/sessions/{sid}/pid", {"pid": ppid, "ppid": None})

    if etype == "agent-turn-complete":
        events.append({"type": "state_change",
                       "data": {"state": "turn_complete",
                                "turn_id": payload.get("turn-id")}})

    _post("/v1/events", {"events": [
        {"agent": "codex", "session_id": sid, **e} for e in events]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
