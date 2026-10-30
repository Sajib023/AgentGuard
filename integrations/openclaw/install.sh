#!/usr/bin/env bash
# Install the AgentGuard plugin for OpenClaw.
#
# Links this directory into the OpenClaw plugin registry, enables it, and
# merges the required plugins.entries["agentguard"] block (with conversation
# access for the before_agent_run / session_end hooks) into openclaw.json.
#
# Usage: ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCLAW_CONFIG="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"

command -v openclaw >/dev/null 2>&1 || {
  echo "error: openclaw CLI not found — install OpenClaw first (https://openclaw.ai/install.sh)" >&2
  exit 1
}

echo "► linking plugin source: $SCRIPT_DIR"
openclaw plugins install --link "$SCRIPT_DIR" --force
openclaw plugins enable agentguard || true

echo "► merging agentguard entry into $OPENCLAW_CONFIG"
merge_entry() {
  python3 - "$OPENCLAW_CONFIG" <<'PY'
import json, os, pathlib, sys

cfg_path = pathlib.Path(sys.argv[1])
canonical = {
    "enabled": True,
    "hooks": {"allowConversationAccess": True},
    "config": {
        "mode": os.environ.get("AGENTGUARD_MODE", "enforce"),
        "url": os.environ.get("AGENTGUARD_URL", "http://127.0.0.1:8907"),
    },
}
try:
    doc = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
except Exception:
    print("NOT_STRICT_JSON")
    raise SystemExit(0)

plugins = doc.setdefault("plugins", {})
entries = plugins.setdefault("entries", {})
old = entries.get("agentguard")
# Merge conservatively: preserve operator-set fields, refresh the shape of ours.
if isinstance(old, dict):
    merged = {**canonical, **old}
    merged["hooks"] = {**canonical["hooks"], **(old.get("hooks") or {})}
    merged["config"] = {**canonical["config"], **(old.get("config") or {})}
    entries["agentguard"] = merged
else:
    entries["agentguard"] = canonical
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print("MERGED")
PY
}

OUTPUT="$(merge_entry 2>/dev/null || true)"
if [[ "$OUTPUT" == "MERGED" ]]; then
  echo "merged:    $OPENCLAW_CONFIG"
else
  echo
  echo "Your openclaw.json is not strict JSON (JSON5 with comments?) —"
  echo "merge this block manually into it:"
  cat <<'EOF'

  {
    "plugins": {
      "entries": {
        "agentguard": {
          "enabled": true,
          "hooks": { "allowConversationAccess": true },
          "config": { "mode": "enforce", "url": "http://127.0.0.1:8907" }
        }
      }
    }
  }

EOF
fi

echo "► reloading plugin"
openclaw plugins reload agentguard || true

echo
echo "Verify on the dashboard: http://127.0.0.1:8907/"
echo "Plugin runtime check:    openclaw plugins inspect agentguard --runtime --json"
