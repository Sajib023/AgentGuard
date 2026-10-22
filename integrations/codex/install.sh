#!/usr/bin/env bash
# Install the AgentGuard hook adapter for Codex CLI (user-global scope).
#
# Codex hooks: ~/.codex/hooks.json is loaded for EVERY project (project-local
# .codex/ layers are only loaded when trusted, and the `notify` key cannot be
# project-scoped at all — notifications belong in user config).
#
# BEFORE these hooks run, Codex requires trust review:
#   run /hooks inside Codex, review + trust the AgentGuard entries
#   (or start once with --dangerously-bypass-hook-trust).
set -euo pipefail

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="$SCRIPT_DIR/hooks/agentguard_codex_hook.py"

mkdir -p "$CODEX_HOME/hooks"
cp "$HOOK_SRC" "$CODEX_HOME/hooks/agentguard_codex_hook.py"
echo "installed: $CODEX_HOME/hooks/agentguard_codex_hook.py"

HOOKS_JSON="$CODEX_HOME/hooks.json"
if [[ -e "$HOOKS_JSON" ]]; then
  echo
  echo "NOT installed: $HOOKS_JSON already exists — merge manually instead of"
  echo "clobbering your existing hooks. Reference definition:"
  echo "  $SCRIPT_DIR/hooks.json.example"
  echo
  echo "Required events (type=command, script above):"
  echo "  SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,"
  echo "  PermissionRequest, SubagentStart, SubagentStop, Stop, SessionEnd"
  exit 0
fi

python3 - "$SCRIPT_DIR/hooks.json.example" "$HOOKS_JSON" <<'PY'
import json, os, pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
script = str(dst.parent / "hooks" / "agentguard_codex_hook.py")
doc = json.loads(src.read_text())
doc.pop("_comment", None)
for groups in doc.get("hooks", {}).values():
    for g in groups:
        for h in g.get("hooks", []):
            h["command"] = "python3 " + script
dst.write_text(json.dumps(doc, indent=2) + "\n")
PY

echo "installed: $HOOKS_JSON"
echo
echo "NEXT: open Codex and run /hooks — review + trust the AgentGuard hooks."
echo "Without trust, Codex will skip them (policy: hooks must be reviewed)."
echo "Verify on the dashboard: http://127.0.0.1:8907/"
