#!/usr/bin/env bash
# Install the AgentGuard hook adapter for Google Antigravity.
#
# Copies the hook into ~/.agentguard and merges the lifecycle wiring into
# Antigravity's global hooks.json (~/.gemini/config/hooks.json). Pass
# --workspace /path/to/project to additionally wire .agents/hooks.json there.
#
# Usage:  ./install.sh [--workspace /path/to/project] [--mcp]
set -euo pipefail

AGENTGUARD_HOME="${AGENTGUARD_HOME:-$HOME/.agentguard}"
GEMINI_DIR="${ANTIGRAVITY_CONFIG_DIR:-$HOME/.gemini/config}"
WORKSPACE=""
WIRE_MCP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --mcp) WIRE_MCP=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="$SCRIPT_DIR/hooks/agentguard_antigravity_hook.py"

mkdir -p "$AGENTGUARD_HOME/hooks" "$GEMINI_DIR"
cp "$HOOK_SRC" "$AGENTGUARD_HOME/hooks/agentguard_antigravity_hook.py"
chmod +x "$AGENTGUARD_HOME/hooks/agentguard_antigravity_hook.py"

HOOK_CMD="$AGENTGUARD_HOME/hooks/agentguard_antigravity_hook.py"

merge_into() {
  python3 - "$1" "$HOOK_CMD" <<'PY'
import json, pathlib, sys

dst_raw, hook = sys.argv[1], sys.argv[2]
dst = pathlib.Path(dst_raw)
doc = {}
if dst.is_file():
    try:
        loaded = json.loads(dst.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            doc = loaded
    except Exception:
        pass

# Strip any stray agentguard commands from other hook-sets, then install a
# fresh "agentguard" hook-set across every supported lifecycle event.
def strip(node):
    if isinstance(node, list):
        return [strip(x) for x in node if not (
            isinstance(x, dict) and "agentguard_antigravity_hook.py" in str(x.get("command", "")))]
    if isinstance(node, dict):
        inner = node.get("hooks")
        if isinstance(inner, list):
            kept = strip(inner)
            return {**node, "hooks": kept} if kept else None
        return {k: strip(v) for k, v in node.items() if k != "hooks" or not isinstance(v, list) or strip(v)}
    return node

doc = {k: v for k, v in ((k, strip(v)) for k, v in doc.items()) if v is not None}
hook_entry = {"type": "command", "command": f"python3 {hook}", "timeout": 35}
doc["agentguard"] = {
    "SessionStart":  [{"type": "command", "command": f"python3 {hook} SessionStart",  "timeout": 15}],
    "PreToolUse":    [{"matcher": "", "hooks": [{"type": "command", "command": f"python3 {hook} PreToolUse",    "timeout": 35}]}],
    "PostToolUse":   [{"matcher": "", "hooks": [{"type": "command", "command": f"python3 {hook} PostToolUse",   "timeout": 30}]}],
    "PreInvocation": [{"type": "command", "command": f"python3 {hook} PreInvocation", "timeout": 15}],
    "Stop":          [{"type": "command", "command": f"python3 {hook} Stop",          "timeout": 15}],
}
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
PY
}

merge_into "$GEMINI_DIR/hooks.json"
echo "installed: $AGENTGUARD_HOME/hooks/agentguard_antigravity_hook.py"
echo "merged:    $GEMINI_DIR/hooks.json"

if [[ -n "$WORKSPACE" ]]; then
  merge_into "$WORKSPACE/.agents/hooks.json"
  echo "merged:    $WORKSPACE/.agents/hooks.json"
fi

if [[ -n "$WIRE_MCP" ]]; then
  sed "s|~/.agentguard|$AGENTGUARD_HOME|g" "$SCRIPT_DIR/mcp_config.json.example" \
    > "$GEMINI_DIR/mcp_config.agentguard.json"
  echo "mcp:       $GEMINI_DIR/mcp_config.agentguard.json"
  echo "           (merge its mcpServers entries into mcp_config.json to enable)"
fi

echo
echo "Verify on the dashboard: http://127.0.0.1:8907/"
