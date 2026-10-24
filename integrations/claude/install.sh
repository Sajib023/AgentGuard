#!/usr/bin/env bash
# Install the AgentGuard hook adapter for Claude Code (merges into ~/.claude/settings.json).
set -euo pipefail

AGENTGUARD_HOME="${AGENTGUARD_HOME:-$HOME/.agentguard}"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="$SCRIPT_DIR/hooks/agentguard_hook.py"

mkdir -p "$AGENTGUARD_HOME/hooks" "$CLAUDE_DIR"
cp "$HOOK_SRC" "$AGENTGUARD_HOME/hooks/agentguard_hook.py"
chmod +x "$AGENTGUARD_HOME/hooks/agentguard_hook.py"

SETTINGS_JSON="$CLAUDE_DIR/settings.json"

python3 - "$AGENTGUARD_HOME/hooks/agentguard_hook.py" "$SETTINGS_JSON" <<'PY'
import json, pathlib, sys
hook_script, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
cmd = f"python3 {hook_script}"
doc = {}
if dst.is_file():
    try:
        loaded = json.loads(dst.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            doc = loaded
    except Exception:
        pass
hooks_map = doc.setdefault("hooks", {})
for ev in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"):
    existing = hooks_map.get(ev, []) if isinstance(hooks_map.get(ev), list) else []
    cleaned = []
    for grp in existing:
        if isinstance(grp, dict) and isinstance(grp.get("hooks"), list):
            kept = [h for h in grp["hooks"] if not (isinstance(h, dict) and "agentguard_hook.py" in str(h.get("command", "")))]
            if kept:
                gcopy = dict(grp)
                gcopy["hooks"] = kept
                cleaned.append(gcopy)
        else:
            cleaned.append(grp)
    cleaned.append({"hooks": [{"type": "command", "command": cmd}]})
    hooks_map[ev] = cleaned
dst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY

echo "installed: $AGENTGUARD_HOME/hooks/agentguard_hook.py"
echo "merged:    $SETTINGS_JSON"
