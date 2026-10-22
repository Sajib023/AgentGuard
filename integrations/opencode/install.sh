#!/usr/bin/env bash
# Install the AgentGuard OpenCode plugin into a project (default) or globally.
#
#   ./install.sh [--project DIR | --global]
#
# Project:  <DIR>/.opencode/plugins/agentguard/agentguard-plugin.js  (auto-loaded)
# Global:   ~/.config/opencode/plugin/agentguard-plugin.js + plugins entry note
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$ROOT/plugin/agentguard-plugin.js"
MODE="--project"
TARGET_DIR="."
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) MODE="--project"; TARGET_DIR="${2:-.}"; shift 2;;
    --global) MODE="--global"; shift;;
    *) echo "unknown arg $1"; exit 1;;
  esac
done

if [[ "$MODE" == "--project" ]]; then
  DEST="$TARGET_DIR/.opencode/plugins/agentguard"
  mkdir -p "$DEST"
  # OpenCode auto-loads the package entry index.js inside the plugin dir
  cp "$PLUGIN" "$DEST/index.js"
  echo "✔ installed: $DEST/index.js"
  echo "  OpenCode auto-loads project plugins from .opencode/plugins/."
  echo "  Start the service first:  agentguard serve   (default port 8907)"
else
  GLOBAL_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugin"
  mkdir -p "$GLOBAL_DIR"
  cp "$PLUGIN" "$GLOBAL_DIR/agentguard-plugin.js"
  echo "✔ installed: $GLOBAL_DIR/agentguard-plugin.js"
  cat <<'USAGE'

  For global plugins, register it in ~/.config/opencode/opencode.json:
    { "plugins": ["~/.config/opencode/plugin/agentguard"] }
  (point the entry at the copied file's directory; OpenCode loads the module)
USAGE
fi
