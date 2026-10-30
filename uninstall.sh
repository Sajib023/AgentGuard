#!/usr/bin/env bash
# AgentGuard Clean Uninstaller
#
# Usage (remote one-liner):
#   curl -fsSL https://raw.githubusercontent.com/Sajib023/AgentGuard/main/uninstall.sh | bash
#
# Usage (local):
#   ./uninstall.sh [-y|--yes] [--keep-data] [--purge-model]
set -euo pipefail

AGENTGUARD_HOME="${AGENTGUARD_HOME:-$HOME/.agentguard}"
BIN_DIR="${HOME}/.local/bin"
MODEL="llama-guard3:1b"

ASSUME_YES=0
KEEP_DATA=0
PURGE_MODEL=0

for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --keep-data) KEEP_DATA=1 ;;
    --purge-model) PURGE_MODEL=1 ;;
    -h|--help)
      echo "Usage: uninstall.sh [-y|--yes] [--keep-data] [--purge-model]"
      echo "  -y, --yes        Skip interactive confirmation"
      echo "  --keep-data      Keep ~/.agentguard/events.db (audit logs)"
      echo "  --purge-model    Also remove llama-guard3:1b from Ollama"
      exit 0
      ;;
  esac
done

bold="\033[1m"
green="\033[32m"
cyan="\033[36m"
yellow="\033[33m"
red="\033[31m"
reset="\033[0m"

info() { printf "${cyan}[agentguard]${reset} %s\n" "$*"; }
ok()   { printf "${green}[agentguard] ✓${reset} %s\n" "$*"; }
warn() { printf "${yellow}[agentguard] !${reset} %s\n" "$*"; }

prompt_user() {
  local prompt_msg="$1"
  local reply=""
  if [[ -t 0 ]]; then
    read -r -p "$prompt_msg" reply || true
  elif [[ -e /dev/tty ]] && ( exec </dev/tty ) 2>/dev/null; then
    read -r -p "$prompt_msg" reply < /dev/tty || true
  else
    reply="y"
  fi
  printf "%s" "$reply"
}

printf "\n${bold}🗑️  AgentGuard Uninstaller${reset}\n\n"

if [[ "$ASSUME_YES" != "1" ]]; then
  printf "This will remove:\n"
  printf "  • AgentGuard background daemon & boot services (systemd / cron)\n"
  printf "  • Agent hooks for OpenCode, Claude Code, Codex CLI, Antigravity, and OpenClaw\n"
  printf "  • Global CLI wrapper (%s/agentguard)\n" "$BIN_DIR"
  if [[ "$KEEP_DATA" == "1" ]]; then
    printf "  • Application files in %s (preserving events.db)\n" "$AGENTGUARD_HOME"
  else
    printf "  • All runtime data in %s\n" "$AGENTGUARD_HOME"
  fi
  printf "\n"

  CONFIRM="$(prompt_user "Are you sure you want to uninstall AgentGuard? [y/N]: ")"
  case "$CONFIRM" in
    [yY]|[yY][eE][sS]) ok "Proceeding with uninstallation..." ;;
    *) warn "Uninstallation cancelled."; exit 0 ;;
  esac
fi

# 1. Stop service & disable boot auto-start
info "Stopping running services and disabling boot auto-start..."
if command -v systemctl >/dev/null 2>&1; then
  if systemctl --user is-active agentguard.service >/dev/null 2>&1; then
    systemctl --user stop agentguard.service 2>/dev/null || true
  fi
  if systemctl --user is-enabled agentguard.service >/dev/null 2>&1; then
    systemctl --user disable agentguard.service 2>/dev/null || true
  fi
  rm -f "$HOME/.config/systemd/user/agentguard.service"
  rm -f "$HOME/.config/systemd/user/agentguard-ollama.service"
  systemctl --user daemon-reload 2>/dev/null || true
fi

# Stop manual pid daemon if running
PIDFILE="$AGENTGUARD_HOME/agentguard.pid"
if [[ -f "$PIDFILE" ]]; then
  PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$PID" && "$PID" =~ ^[0-9]+$ ]]; then
    kill "$PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi

# Remove crontab reboot entries if any
if command -v crontab >/dev/null 2>&1; then
  EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
  if [[ -n "$EXISTING_CRON" && "$EXISTING_CRON" =~ boot-start.sh ]]; then
    printf "%s\n" "$EXISTING_CRON" | grep -v "boot-start.sh" | crontab - 2>/dev/null || true
  fi
fi
ok "Services stopped and boot configuration removed"

# 2. Unregister agent hooks cleanly
info "Removing hooks from OpenCode, Claude Code, Codex CLI, Antigravity, and OpenClaw..."

# OpenCode plugin
OPENCODE_PLUGIN="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/plugins/agentguard"
if [[ -d "$OPENCODE_PLUGIN" ]]; then
  rm -rf "$OPENCODE_PLUGIN"
  ok "Removed OpenCode plugin ($OPENCODE_PLUGIN)"
fi

# Claude Code hooks
CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
if [[ -f "$CLAUDE_SETTINGS" ]] && command -v python3 >/dev/null 2>&1; then
  python3 - "$CLAUDE_SETTINGS" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    doc = json.loads(p.read_text(encoding="utf-8"))
    hooks_map = doc.get("hooks", {})
    changed = False
    for ev in list(hooks_map.keys()):
        groups = hooks_map[ev]
        if isinstance(groups, list):
            cleaned = []
            for g in groups:
                if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                    kept = [h for h in g["hooks"] if "agentguard_hook.py" not in str(h.get("command", ""))]
                    if kept:
                        g_copy = dict(g)
                        g_copy["hooks"] = kept
                        cleaned.append(g_copy)
                    else:
                        changed = True
                else:
                    cleaned.append(g)
            hooks_map[ev] = cleaned
            if not cleaned:
                del hooks_map[ev]
                changed = True
    if changed:
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
except Exception:
    pass
PY
  ok "Removed AgentGuard hooks from $CLAUDE_SETTINGS"
fi

# Codex CLI hooks
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CODEX_HOOKS="$CODEX_HOME/hooks.json"
if [[ -f "$CODEX_HOOKS" ]] && command -v python3 >/dev/null 2>&1; then
  python3 - "$CODEX_HOOKS" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    doc = json.loads(p.read_text(encoding="utf-8"))
    hooks_map = doc.get("hooks", {})
    changed = False
    for ev in list(hooks_map.keys()):
        groups = hooks_map[ev]
        if isinstance(groups, list):
            cleaned = []
            for g in groups:
                if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                    kept = [h for h in g["hooks"] if "agentguard_codex_hook.py" not in str(h.get("command", ""))]
                    if kept:
                        g_copy = dict(g)
                        g_copy["hooks"] = kept
                        cleaned.append(g_copy)
                    else:
                        changed = True
                else:
                    cleaned.append(g)
            hooks_map[ev] = cleaned
            if not cleaned:
                del hooks_map[ev]
                changed = True
    if changed:
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
except Exception:
    pass
PY
  rm -f "$CODEX_HOME/hooks/agentguard_codex_hook.py"
  ok "Removed AgentGuard hooks from $CODEX_HOOKS"
fi

# Google Antigravity hooks
ANTIGRAVITY_HOOKS="${ANTIGRAVITY_CONFIG_DIR:-$HOME/.gemini/config}/hooks.json"
if [[ -f "$ANTIGRAVITY_HOOKS" ]] && command -v python3 >/dev/null 2>&1; then
  python3 - "$ANTIGRAVITY_HOOKS" <<'PY'
import json, pathlib, sys, re

p = pathlib.Path(sys.argv[1])
marker = "agentguard_antigravity_hook.py"

def strip(node):
    if isinstance(node, dict):
        if isinstance(node.get("command"), str) and marker in node["command"]:
            return None  # signal drop
        if isinstance(node.get("hooks"), list):
            kept = [h for h in (strip_rep(x) for x in node["hooks"]) if h is not None]
            return {**node, "hooks": kept} if kept else None
        return dict(node)
    return node

def strip_rep(node):
    if isinstance(node, list):
        out = []
        for x in node:
            v = strip_rep(x)
            if v is not None:
                out.append(v)
        return out
    return strip(node)

try:
    doc = json.loads(p.read_text(encoding="utf-8"))
    changed = False
    if isinstance(doc, dict):
        new_doc = {}
        for set_name, events in doc.items():
            if isinstance(events, dict):
                new_events = {}
                for ev_name, entries in events.items():
                    if isinstance(entries, list):
                        kept = [e for e in (strip_rep(e) for e in entries) if e is not None]
                        if kept:
                            new_events[ev_name] = kept
                            if kept != entries:
                                changed = True
                        else:
                            changed = True
                    else:
                        new_events[ev_name] = entries
                if new_events:
                    new_doc[set_name] = new_events
            else:
                new_doc[set_name] = events
        if new_doc != doc:
            changed = True
            doc = new_doc
    if changed and doc:
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    elif changed and not doc:
        p.write_text("{}\n", encoding="utf-8")
except Exception:
    pass
PY
  ok "Removed AgentGuard hooks from $ANTIGRAVITY_HOOKS"
fi

# OpenClaw plugin
if command -v openclaw >/dev/null 2>&1; then
  openclaw plugins remove agentguard >/dev/null 2>&1 \
    || openclaw plugins uninstall agentguard >/dev/null 2>&1 \
    || true
  ok "Removed agentguard plugin from OpenClaw"
fi
OPENCLAW_CFG="${OPENCLAW_CONFIG:-$HOME/.openclaw/openclaw.json}"
if [[ -f "$OPENCLAW_CFG" ]] && command -v python3 >/dev/null 2>&1; then
  python3 - "$OPENCLAW_CFG" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    doc = json.loads(p.read_text(encoding="utf-8"))
    entries = (doc or {}).get("plugins", {}).get("entries", {})
    if isinstance(entries, dict) and "agentguard" in entries:
        del entries["agentguard"]
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
except Exception:
    pass
PY
fi

# 3. Remove binary symlink / wrapper
if [[ -f "$BIN_DIR/agentguard" ]]; then
  rm -f "$BIN_DIR/agentguard"
  ok "Removed CLI wrapper ($BIN_DIR/agentguard)"
fi

# 4. Remove runtime directory / data
if [[ -d "$AGENTGUARD_HOME" ]]; then
  if [[ "$KEEP_DATA" == "1" ]]; then
    rm -rf "$AGENTGUARD_HOME/app" "$AGENTGUARD_HOME/venv" "$AGENTGUARD_HOME/hooks" "$AGENTGUARD_HOME/boot-start.sh"
    ok "Removed application files (preserved $AGENTGUARD_HOME/events.db)"
  else
    rm -rf "$AGENTGUARD_HOME"
    ok "Removed $AGENTGUARD_HOME"
  fi
fi

# 5. Optional Ollama model purge
if [[ "$PURGE_MODEL" == "1" ]] && command -v ollama >/dev/null 2>&1; then
  info "Purging model $MODEL from Ollama..."
  ollama rm "$MODEL" 2>/dev/null || true
  ok "Removed $MODEL from Ollama"
fi

printf "\n${bold}${green}✓ AgentGuard has been completely uninstalled.${reset}\n\n"
