#!/usr/bin/env bash
# Install the AgentGuard OpenCode plugin.
#
#   ./install.sh              project level: this directory only
#   ./install.sh --global     every OpenCode session on this machine
#
# Locations (per OpenCode plugin discovery, auto-loaded at startup):
#   project:  <dir>/.opencode/plugins/agentguard/index.js
#   global:   ~/.config/opencode/plugins/agentguard/index.js
#
# Note: OpenCode loads hooks from BOTH dirs (global first). Duplicates are
# prevented by the plugin's exactly-once guard, but installing globally and
# keeping a project copy means updating both after edits. One is enough.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$ROOT/plugin/agentguard-plugin.js"
MODE="--project"
TARGET_DIR="."
[[ $# -gt 0 ]] || set -- --project
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      MODE="--project"
      if [[ -n "${2-}" && "$2" != -* ]]; then TARGET_DIR="$2"; shift 2; else shift; fi
      ;;
    --global) MODE="--global"; shift;;
    -h|--help) echo "usage: ./install.sh [--project DIR | --global]"; exit 0;;
    *) echo "unknown arg: $1"; echo "usage: ./install.sh [--project DIR | --global]"; exit 1;;
  esac
done

if [[ "$MODE" == "--project" ]]; then
  DEST="$TARGET_DIR/.opencode/plugins/agentguard"
  mkdir -p "$DEST"
  cp "$PLUGIN" "$DEST/index.js"
  echo "installed (project): $DEST/index.js"
  echo "  covers sessions started inside $TARGET_DIR only"
  echo "  for every project instead:  $(basename "$0") --global"
else
  GLOBAL="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugins"
  DEST="$GLOBAL/agentguard"
  mkdir -p "$DEST"
  cp "$PLUGIN" "$DEST/index.js"
  echo "installed (global): $DEST/index.js"
  echo "  covers every OpenCode session on this machine, any directory"
  echo "  (no config entry needed; OpenCode auto-loads this dir at startup)"
fi
echo "  restart OpenCode (or run 'opencode service restart') to load it"
echo "  start the AgentGuard core service once:  agentguard serve"
