#!/usr/bin/env bash
# AgentGuard One-Command Installer & Bootstrapper
#
# Usage (remote one-liner):
#   curl -fsSL https://raw.githubusercontent.com/Sajib023/AgentGuard/main/install.sh | bash
#
# Usage (local checkout):
#   ./install.sh [--no-start] [--pull-model]
#
# Environment overrides:
#   AGENTGUARD_HOME       Base runtime dir (default: ~/.agentguard)
#   AGENTGUARD_REPO_URL   Git URL when running via curl | bash
#   AGENTGUARD_BRANCH     Git branch when cloning (default: master or main)
#   AGENTGUARD_PORT       Service port (default: 8907)
set -euo pipefail

AGENTGUARD_HOME="${AGENTGUARD_HOME:-$HOME/.agentguard}"
AGENTGUARD_PORT="${AGENTGUARD_PORT:-8907}"
REPO_URL="${AGENTGUARD_REPO_URL:-https://github.com/Sajib023/AgentGuard.git}"
BIN_DIR="${HOME}/.local/bin"

START_DAEMON=1
PULL_MODEL=0

for arg in "$@"; do
  case "$arg" in
    --no-start)   START_DAEMON=0 ;;
    --pull-model) PULL_MODEL=1 ;;
    -h|--help)
      echo "Usage: install.sh [--no-start] [--pull-model]"
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

info()  { printf "${cyan}[agentguard]${reset} %s\n" "$*"; }
ok()    { printf "${green}[agentguard] ✓${reset} %s\n" "$*"; }
warn()  { printf "${yellow}[agentguard] !${reset} %s\n" "$*"; }
fail()  { printf "${red}[agentguard] ✗ %s${reset}\n" "$*" >&2; exit 1; }

printf "\n${bold}⚡ AgentGuard One-Step Installer${reset}\n"
printf "   Local-First Runtime Firewall · Threat-RAG & GraphRAG · Circuit Breaker · MCP Hub\n\n"

# 1. Verify Python >= 3.11
if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required (Python 3.11+)."
fi

PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))')"
PY_VER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if [[ "$PY_OK" != "1" ]]; then
  fail "Python 3.11+ is required (found Python $PY_VER)."
fi
ok "Python $PY_VER detected"

# 2. Locate or clone the AgentGuard repository
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
LOCAL_DIR=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  CANDIDATE="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
  if [[ -f "$CANDIDATE/core/pyproject.toml" ]]; then
    LOCAL_DIR="$CANDIDATE"
  fi
fi
if [[ -z "$LOCAL_DIR" && -f "./core/pyproject.toml" ]]; then
  LOCAL_DIR="$(pwd)"
fi

mkdir -p "$AGENTGUARD_HOME" "$BIN_DIR"

if [[ -n "$LOCAL_DIR" ]]; then
  APP_DIR="$LOCAL_DIR"
  VENV_DIR="$APP_DIR/.venv"
  info "Using local repository at $APP_DIR"
else
  APP_DIR="$AGENTGUARD_HOME/app"
  VENV_DIR="$AGENTGUARD_HOME/venv"
  if ! command -v git >/dev/null 2>&1; then
    fail "git is required to download AgentGuard into $APP_DIR"
  fi
  if [[ -d "$APP_DIR/.git" ]]; then
    info "Updating existing AgentGuard checkout in $APP_DIR..."
    git -C "$APP_DIR" pull --ff-only || warn "git pull skipped (working tree has local changes)"
  else
    info "Cloning AgentGuard from $REPO_URL into $APP_DIR..."
    rm -rf "$APP_DIR"
    git clone --depth 1 "$REPO_URL" "$APP_DIR"
  fi
fi

# 3. Create Python virtual environment & install AgentGuard Core
if ! "$VENV_DIR/bin/python" -c "import sys" >/dev/null 2>&1; then
  info "Creating Python virtual environment at $VENV_DIR..."
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

info "Installing AgentGuard core package and dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$APP_DIR/core"
ok "AgentGuard core installed ($("$VENV_DIR/bin/agentguard" version))"

# 4. Build dashboard bundle if missing and npm is available
if [[ -f "$APP_DIR/dashboard/dist/index.html" ]]; then
  ok "Dashboard bundle ready ($APP_DIR/dashboard/dist)"
elif command -v npm >/dev/null 2>&1 && [[ -f "$APP_DIR/dashboard/package.json" ]]; then
  info "Building AMOLED Developer Dashboard (React + Vite)..."
  (
    cd "$APP_DIR/dashboard"
    if [[ ! -d node_modules ]]; then
      npm install --no-audit --no-fund --silent
    fi
    npm run build --silent
  )
  ok "Dashboard built at $APP_DIR/dashboard/dist"
else
  warn "dashboard/dist not found and npm is not installed (API will run headless)"
fi

# 5. Create global wrapper in ~/.local/bin/agentguard
WRAPPER="$BIN_DIR/agentguard"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
export AGENTGUARD_REPO_ROOT="$APP_DIR"
export AGENTGUARD_DASHBOARD_DIR="$APP_DIR/dashboard/dist"
exec "$VENV_DIR/bin/agentguard" "\$@"
EOF
chmod +x "$WRAPPER"
ok "CLI linked at $WRAPPER"

# 6. Auto-configure coding agent hooks (OpenCode, Claude Code, Codex CLI)
info "Configuring coding agent integrations (OpenCode, Claude Code, Codex CLI)..."
SETUP_ARGS=()
if [[ "$PULL_MODEL" == "1" ]]; then
  SETUP_ARGS+=("--pull-model")
fi
"$WRAPPER" setup "${SETUP_ARGS[@]}"
ok "Agent hooks wired"

# 7. Start the AgentGuard daemon & verify health
if [[ "$START_DAEMON" == "1" ]]; then
  info "Starting AgentGuard background service on port $AGENTGUARD_PORT..."
  "$WRAPPER" serve --daemon --port "$AGENTGUARD_PORT"
  ok "AgentGuard service is live at http://127.0.0.1:${AGENTGUARD_PORT}/"
fi

printf "\n${bold}${green}🎉 AgentGuard is fully set up and protecting your agents!${reset}\n"
printf "   • ${bold}Dashboard:${reset}    http://127.0.0.1:${AGENTGUARD_PORT}/\n"
printf "   • ${bold}Check Status:${reset} agentguard status\n"
printf "   • ${bold}Env Doctor:${reset}   agentguard doctor\n"
printf "   • ${bold}Stop Server:${reset}  agentguard stop\n"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf "\n   ${yellow}Note:${reset} Add ~/.local/bin to your PATH if needed:\n"
  printf "   export PATH=\"\$HOME/.local/bin:\$PATH\"\n"
fi
printf "\n"
