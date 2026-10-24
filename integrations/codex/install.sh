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

python3 - "$SCRIPT_DIR/hooks.json.example" "$HOOKS_JSON" <<'PY'
import json, pathlib, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
script = "python3 " + str(dst.parent / "hooks" / "agentguard_codex_hook.py")
template = json.loads(src.read_text(encoding="utf-8"))
doc = {}
if dst.is_file():
    try:
        loaded = json.loads(dst.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            doc = loaded
    except Exception:
        pass
doc.setdefault("description", template.get("description", "AgentGuard lifecycle hooks"))
hooks_map = doc.setdefault("hooks", {})
for ev, groups in template.get("hooks", {}).items():
    new_groups = json.loads(json.dumps(groups))
    for g in new_groups:
        g.pop("_comment", None)
        for h in g.get("hooks", []):
            h["command"] = script
    existing = hooks_map.get(ev, []) if isinstance(hooks_map.get(ev), list) else []
    cleaned = []
    for grp in existing:
        if isinstance(grp, dict) and isinstance(grp.get("hooks"), list):
            kept = [h for h in grp["hooks"] if not (isinstance(h, dict) and "agentguard_codex_hook.py" in str(h.get("command", "")))]
            if kept:
                gcopy = dict(grp)
                gcopy["hooks"] = kept
                cleaned.append(gcopy)
        else:
            cleaned.append(grp)
    cleaned.extend(new_groups)
    hooks_map[ev] = cleaned
dst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY

echo "installed (merged): $HOOKS_JSON"
echo
echo "NEXT: open Codex and run /hooks — review + trust the AgentGuard hooks."
echo "Without trust, Codex will skip them (policy: hooks must be reviewed)."
echo "Verify on the dashboard: http://127.0.0.1:8907/"
