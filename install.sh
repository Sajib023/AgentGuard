#!/usr/bin/env bash
# AgentGuard One-Command Installer & Hardware-Verified AI Model Bootstrapper
#
# Usage (remote one-liner):
#   curl -fsSL https://raw.githubusercontent.com/Sajib023/AgentGuard/main/install.sh | bash
#
# Usage (with options):
#   curl -fsSL https://raw.githubusercontent.com/Sajib023/AgentGuard/main/install.sh | bash -s -- [--model llama-guard3:1b] [--yes]
#   ./install.sh [--model llama-guard3:1b] [--yes] [--no-start]
#
# Environment overrides:
#   AGENTGUARD_HOME            Base runtime dir (default: ~/.agentguard)
#   AGENTGUARD_REPO_URL        Git URL when running via curl | bash
#   AGENTGUARD_PORT            Service port (default: 8907)
#   AGENTGUARD_MODEL           Ollama AI model to install (default: llama-guard3:1b)
#   AGENTGUARD_MIN_RAM_MB      Override minimum total RAM in MB (default: 3584 for 1b)
#   AGENTGUARD_MIN_AVAIL_RAM_MB Override minimum available RAM in MB (default: 1024 for 1b)
#   AGENTGUARD_MIN_DISK_MB     Override minimum free disk space in MB (default: 5120 for 1b)
#   AGENTGUARD_MIN_CPU_CORES   Override minimum CPU core count (default: 2)
#   AGENTGUARD_ASSUME_YES      Set to 1 to skip interactive permission prompt
set -euo pipefail

AGENTGUARD_HOME="${AGENTGUARD_HOME:-$HOME/.agentguard}"
AGENTGUARD_PORT="${AGENTGUARD_PORT:-8907}"
AGENTGUARD_MODEL="${AGENTGUARD_MODEL:-llama-guard3:1b}"
OLLAMA_HOST_URL="${OLLAMA_HOST_URL:-http://127.0.0.1:11434}"
REPO_URL="${AGENTGUARD_REPO_URL:-https://github.com/Sajib023/AgentGuard.git}"
BIN_DIR="${HOME}/.local/bin"

START_DAEMON=1
ASSUME_YES="${AGENTGUARD_ASSUME_YES:-0}"
HW_CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      AGENTGUARD_MODEL="${2:?--model requires a model name}"
      shift 2
      ;;
    -y|--yes)
      ASSUME_YES=1
      shift
      ;;
    --no-start)
      START_DAEMON=0
      shift
      ;;
    --hwcheck-only)
      HW_CHECK_ONLY=1
      shift
      ;;
    -h|--help)
      echo "Usage: install.sh [--model MODEL] [-y|--yes] [--no-start] [--hwcheck-only]"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

bold="\033[1m"
dim="\033[2m"
green="\033[32m"
cyan="\033[36m"
yellow="\033[33m"
red="\033[31m"
reset="\033[0m"

info()    { printf "${cyan}[agentguard]${reset} %s\n" "$*"; }
ok()      { printf "${green}[agentguard] ✓${reset} %s\n" "$*"; }
warn()    { printf "${yellow}[agentguard] !${reset} %s\n" "$*"; }
fail()    { printf "${red}[agentguard] ✗ %s${reset}\n" "$*" >&2; exit 1; }
section() { printf "\n${bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${reset}\n  ${bold}%s${reset}\n${bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${reset}\n" "$*"; }

printf "\n${bold}⚡ AgentGuard Setup & Hardware-Verified Local AI Installer${reset}\n"
printf "   Local-First Runtime Firewall · Threat-RAG & GraphRAG · Circuit Breaker · MCP Hub\n"

# Ensure python3 >= 3.11 is present for pre-flight checks & runtime
if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 is required (Python 3.11+). Please install python3 first."
fi

PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 11)))')"
PY_VER="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
if [[ "$PY_OK" != "1" ]]; then
  fail "Python 3.11+ is required (found Python $PY_VER)."
fi

# ==============================================================================
# STEP 1: HARDWARE COMPATIBILITY CHECK (Before downloading or installing anything)
# ==============================================================================
section "Step 1/5 · Hardware Compatibility Check (Selected Model: ${AGENTGUARD_MODEL})"
info "Inspecting system CPU, RAM, and available disk storage..."

set +e
AGENTGUARD_MODEL="$AGENTGUARD_MODEL" AGENTGUARD_HOME="$AGENTGUARD_HOME" python3 - <<'PY'
import os
import pathlib
import platform
import shutil
import subprocess
import sys

model = os.environ.get("AGENTGUARD_MODEL", "llama-guard3:1b")
target_home = os.environ.get("AGENTGUARD_HOME") or os.path.expanduser("~/.agentguard")
low = model.lower()

# Determine hardware requirements based on model parameter scale
if any(tag in low for tag in (":7b", ":8b", ":9b", ":13b", ":14b")):
    def_ram_mb, def_avail_mb, def_disk_mb, def_cores = 7680, 4096, 10240, 4
elif any(tag in low for tag in (":3b", ":4b")):
    def_ram_mb, def_avail_mb, def_disk_mb, def_cores = 5632, 2048, 7168, 2
else:
    # 1b / 1.5b class (default llama-guard3:1b)
    def_ram_mb, def_avail_mb, def_disk_mb, def_cores = 3584, 1024, 5120, 2

min_ram_mb = int(os.environ.get("AGENTGUARD_MIN_RAM_MB", str(def_ram_mb)))
min_avail_mb = int(os.environ.get("AGENTGUARD_MIN_AVAIL_RAM_MB", str(def_avail_mb)))
min_disk_mb = int(os.environ.get("AGENTGUARD_MIN_DISK_MB", str(def_disk_mb)))
min_cores = int(os.environ.get("AGENTGUARD_MIN_CPU_CORES", str(def_cores)))

# 1. CPU Detection
arch = platform.machine().lower()
supported_archs = {"x86_64", "amd64", "aarch64", "arm64"}
arch_ok = arch in supported_archs
cores = os.cpu_count() or 1
cores_ok = cores >= min_cores
cpu_model = platform.processor() or arch or "Unknown CPU"
flags = set()

if os.path.isfile("/proc/cpuinfo"):
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.lower().startswith("model name") and ":" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                elif line.lower().startswith(("flags", "features")) and ":" in line:
                    flags.update(line.split(":", 1)[1].strip().lower().split())
    except Exception:
        pass
elif sys.platform == "darwin":
    try:
        out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        if out:
            cpu_model = out
    except Exception:
        pass

simd_features = []
if arch in ("x86_64", "amd64"):
    for feat in ("avx512f", "avx2", "avx", "sse4_2", "sse4_1"):
        if feat in flags:
            simd_features.append(feat.upper().replace("_", "."))
    simd_ok = bool(simd_features) or not flags
elif arch in ("aarch64", "arm64"):
    simd_features.append("NEON/ASIMD")
    simd_ok = True
else:
    simd_ok = False

cpu_ok = arch_ok and cores_ok and simd_ok
simd_str = ", ".join(simd_features) if simd_features else "64-bit baseline"

# 2. RAM Detection
total_ram_mb = 0
avail_ram_mb = 0
if os.path.isfile("/proc/meminfo"):
    mem = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0]) // 1024
        total_ram_mb = mem.get("MemTotal", 0)
        avail_ram_mb = mem.get("MemAvailable", mem.get("MemFree", 0))
    except Exception:
        pass
elif sys.platform == "darwin":
    try:
        mem_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        total_ram_mb = mem_bytes // (1024 * 1024)
        avail_ram_mb = total_ram_mb // 2
    except Exception:
        pass

ram_ok = (total_ram_mb >= min_ram_mb) and (avail_ram_mb >= min_avail_mb)

# 3. Storage Detection
check_path = pathlib.Path(target_home).expanduser()
while not check_path.exists() and check_path.parent != check_path:
    check_path = check_path.parent
usage = shutil.disk_usage(check_path)
free_disk_mb = usage.free // (1024 * 1024)
total_disk_mb = usage.total // (1024 * 1024)
disk_ok = free_disk_mb >= min_disk_mb

GREEN = "\033[32m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"

def badge(passed: bool) -> str:
    return f"{GREEN}{BOLD}[PASS]{RESET}" if passed else f"{RED}{BOLD}[FAIL]{RESET}"

print()
print(f"  {badge(cpu_ok)}  {BOLD}CPU:{RESET}      {cpu_model}")
print(f"           Detected: arch={arch}, {cores} logical cores, SIMD={simd_str}")
print(f"           Required: arch in (x86_64, arm64), >= {min_cores} cores, 64-bit SIMD support")
print()
print(f"  {badge(ram_ok)}  {BOLD}RAM:{RESET}      {total_ram_mb / 1024:.2f} GB total ({avail_ram_mb / 1024:.2f} GB available)")
print(f"           Detected: {total_ram_mb} MB total / {avail_ram_mb} MB available")
print(f"           Required: >= {min_ram_mb / 1024:.2f} GB ({min_ram_mb} MB) total, >= {min_avail_mb / 1024:.2f} GB ({min_avail_mb} MB) available")
print()
print(f"  {badge(disk_ok)}  {BOLD}Storage:{RESET}  {free_disk_mb / 1024:.2f} GB free on {check_path} (of {total_disk_mb / 1024:.1f} GB total)")
print(f"           Detected: {free_disk_mb} MB free disk space")
print(f"           Required: >= {min_disk_mb / 1024:.2f} GB ({min_disk_mb} MB) free for Ollama + {model} + AgentGuard")
print()

failures = []
if not cpu_ok:
    reasons = []
    if not arch_ok:
        reasons.append(f"unsupported architecture '{arch}' (required: x86_64 or arm64)")
    if not cores_ok:
        reasons.append(f"detected {cores} CPU core(s) vs required minimum {min_cores} cores")
    if not simd_ok:
        reasons.append("CPU lacks required 64-bit SIMD instruction support")
    failures.append(("CPU", "; ".join(reasons)))

if not ram_ok:
    reasons = []
    if total_ram_mb < min_ram_mb:
        reasons.append(
            f"detected {total_ram_mb / 1024:.2f} GB ({total_ram_mb} MB) total RAM vs required minimum {min_ram_mb / 1024:.2f} GB ({min_ram_mb} MB)"
        )
    if avail_ram_mb < min_avail_mb:
        reasons.append(
            f"detected {avail_ram_mb / 1024:.2f} GB ({avail_ram_mb} MB) available RAM vs required minimum {min_avail_mb / 1024:.2f} GB ({min_avail_mb} MB)"
        )
    failures.append(("RAM", "; ".join(reasons)))

if not disk_ok:
    failures.append(
        (
            "Storage",
            f"detected {free_disk_mb / 1024:.2f} GB ({free_disk_mb} MB) free space on {check_path} vs required minimum {min_disk_mb / 1024:.2f} GB ({min_disk_mb} MB)",
        )
    )

if failures:
    print(f"  {RED}{BOLD}✗ COMPATIBILITY RESULT: FAILED ({len(failures)} requirement(s) not met){RESET}")
    for name, detail in failures:
        print(f"    • {BOLD}{name}:{RESET} {detail}")
    print()
    print(f"  {BOLD}Action Taken:{RESET} Ollama and model '{model}' were NOT downloaded or installed.")
    print("  Exiting installation gracefully.")
    sys.exit(2)

print(f"  {GREEN}{BOLD}✓ COMPATIBILITY RESULT: PASSED — Device meets all requirements for {model}.{RESET}")
sys.exit(0)
PY
HW_RC=$?
set -e

if [[ "$HW_RC" -ne 0 ]]; then
  exit 1
fi

if [[ "$HW_CHECK_ONLY" == "1" ]]; then
  exit 0
fi

# ==============================================================================
# EXPLICIT USER PERMISSION PROMPT (Before any download or system modification)
# ==============================================================================
printf "\n${bold}Planned Installation & System Actions:${reset}\n"
printf "  1. Download and install ${bold}Ollama${reset} (if not already installed)\n"
printf "  2. Download AI model ${bold}%s${reset} via Ollama\n" "$AGENTGUARD_MODEL"
printf "  3. Install & configure ${bold}AgentGuard${reset} in %s (+ OpenCode, Claude Code, Codex hooks)\n" "$AGENTGUARD_HOME"
printf "  4. Configure ${bold}Ollama${reset} and ${bold}AgentGuard${reset} to start automatically on device boot\n"
printf "  5. Verify Ollama, model inference, and AgentGuard firewall readiness\n\n"

if [[ "$ASSUME_YES" != "1" ]]; then
  REPLY=""
  if [[ -t 0 ]]; then
    read -r -p "Do you grant permission to proceed with downloading and installing these components? [y/N]: " REPLY || true
  elif [[ -e /dev/tty ]] && ( exec </dev/tty ) 2>/dev/null; then
    read -r -p "Do you grant permission to proceed with downloading and installing these components? [y/N]: " REPLY < /dev/tty || true
  else
    warn "No interactive terminal (/dev/tty) detected for permission prompt."
    warn "Re-run in an interactive terminal or pass '--yes' (or AGENTGUARD_ASSUME_YES=1) to grant permission explicitly."
    exit 1
  fi

  case "$REPLY" in
    [yY]|[yY][eE][sS])
      ok "User permission granted. Starting installation..."
      ;;
    *)
      warn "Permission declined by user. Nothing was downloaded or modified. Exiting gracefully."
      exit 0
      ;;
  esac
else
  ok "Explicit permission flag (--yes / AGENTGUARD_ASSUME_YES=1) provided."
fi

mkdir -p "$AGENTGUARD_HOME" "$BIN_DIR"

# ==============================================================================
# STEP 2: DOWNLOAD & INSTALL OLLAMA + PULL REQUIRED AI MODEL
# ==============================================================================
section "Step 2/5 · Ollama Runtime & AI Model (${AGENTGUARD_MODEL}) Installation"

if command -v ollama >/dev/null 2>&1; then
  ok "Ollama is already installed ($(ollama --version 2>/dev/null || echo 'detected'))"
else
  info "Downloading and installing Ollama from https://ollama.com/install.sh ..."
  curl -fsSL https://ollama.com/install.sh | sh
  ok "Ollama installed ($(ollama --version 2>/dev/null || echo 'ready'))"
fi

# Ensure Ollama daemon is running before pulling the model
wait_for_ollama() {
  local retries="${1:-30}"
  local i=0
  while (( i < retries )); do
    if curl -fsS "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
    (( i += 1 ))
  done
  return 1
}

if ! wait_for_ollama 2; then
  info "Starting Ollama server in the background..."
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    sudo systemctl start ollama 2>/dev/null || true
  fi
  if ! wait_for_ollama 4; then
    nohup ollama serve >"$AGENTGUARD_HOME/ollama.log" 2>&1 &
  fi
  if ! wait_for_ollama 30; then
    fail "Ollama server did not become reachable at ${OLLAMA_HOST_URL} — check $AGENTGUARD_HOME/ollama.log"
  fi
fi
ok "Ollama daemon is active at ${OLLAMA_HOST_URL}"

info "Downloading AI model '${AGENTGUARD_MODEL}' via Ollama (this may take a moment)..."
ollama pull "$AGENTGUARD_MODEL"
ok "AI model '${AGENTGUARD_MODEL}' downloaded successfully"

# ==============================================================================
# STEP 3: INSTALL & CONFIGURE AGENTGUARD + MODEL ENVIRONMENT
# ==============================================================================
section "Step 3/5 · AgentGuard Core, Environment & Coding Agent Hooks"

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

if ! "$VENV_DIR/bin/python" -c "import sys" >/dev/null 2>&1; then
  info "Creating Python virtual environment at $VENV_DIR..."
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

info "Installing AgentGuard core package and dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$APP_DIR/core"
ok "AgentGuard core installed ($("$VENV_DIR/bin/agentguard" version))"

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

# Configure ~/.agentguard/agentguard.yaml with the selected model & Ollama endpoint
CONFIG_FILE="$AGENTGUARD_HOME/agentguard.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  cat > "$CONFIG_FILE" <<EOF
server:
  host: 127.0.0.1
  port: ${AGENTGUARD_PORT}
  db_path: "${AGENTGUARD_HOME}/events.db"

firewall:
  enabled: true
  observe_mode: false
  llm_guard:
    enabled: true
    provider: ollama
    model: "${AGENTGUARD_MODEL}"
    endpoint: "${OLLAMA_HOST_URL}"
    timeout_seconds: 20.0
    on_failure: allow_pass

dashboard:
  dir: "${APP_DIR}/dashboard/dist"
EOF
  ok "Created model & runtime configuration at $CONFIG_FILE"
else
  # Update model in existing config if present
  AGENTGUARD_CFG="$CONFIG_FILE" AGENTGUARD_MODEL="$AGENTGUARD_MODEL" OLLAMA_HOST_URL="$OLLAMA_HOST_URL" "$VENV_DIR/bin/python" - <<'PY'
import os, pathlib, yaml
p = pathlib.Path(os.environ["AGENTGUARD_CFG"])
try:
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        fw = data.setdefault("firewall", {})
        lg = fw.setdefault("llm_guard", {})
        lg["enabled"] = True
        lg["model"] = os.environ["AGENTGUARD_MODEL"]
        lg["endpoint"] = os.environ["OLLAMA_HOST_URL"]
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
except Exception:
    pass
PY
  ok "Updated model configuration in $CONFIG_FILE (model: ${AGENTGUARD_MODEL})"
fi

WRAPPER="$BIN_DIR/agentguard"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
export AGENTGUARD_HOME="$AGENTGUARD_HOME"
export AGENTGUARD_CONFIG="\${AGENTGUARD_CONFIG:-$CONFIG_FILE}"
export AGENTGUARD_REPO_ROOT="$APP_DIR"
export AGENTGUARD_DASHBOARD_DIR="$APP_DIR/dashboard/dist"
exec "$VENV_DIR/bin/agentguard" "\$@"
EOF
chmod +x "$WRAPPER"
ok "CLI linked at $WRAPPER"

info "Configuring coding agent integrations (OpenCode, Claude Code, Codex CLI)..."
"$WRAPPER" setup
ok "Agent hooks wired"

# ==============================================================================
# STEP 4: CONFIGURE AUTO-START ON DEVICE BOOT (Ollama + AgentGuard)
# ==============================================================================
section "Step 4/5 · Configuring Auto-Start on Device Boot"

OLLAMA_BIN="$(command -v ollama)"
BOOT_METHOD="daemon"

# 4a. Ensure Ollama starts automatically on boot and preloads the required model
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  # System-level or user-level systemd
  if systemctl list-unit-files ollama.service >/dev/null 2>&1; then
    if ! systemctl is-enabled ollama.service >/dev/null 2>&1; then
      info "Enabling system-level ollama.service on boot..."
      sudo systemctl enable --now ollama.service 2>/dev/null || true
    else
      sudo systemctl start ollama.service 2>/dev/null || true
    fi
    ok "Ollama systemd service (ollama.service) enabled for device boot"
  else
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/agentguard-ollama.service" <<EOF
[Unit]
Description=Ollama Local AI Runtime (Managed by AgentGuard)
After=network-online.target

[Service]
Type=simple
ExecStart=${OLLAMA_BIN} serve
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now agentguard-ollama.service 2>/dev/null || true
    ok "Configured user systemd service (agentguard-ollama.service) for boot"
  fi

  # 4b. Configure AgentGuard + model warmup service on boot
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/agentguard.service" <<EOF
[Unit]
Description=AgentGuard Local Security Firewall, Threat-RAG & MCP Hub
After=network-online.target

[Service]
Type=simple
Environment="AGENTGUARD_HOME=${AGENTGUARD_HOME}"
Environment="AGENTGUARD_CONFIG=${CONFIG_FILE}"
Environment="AGENTGUARD_REPO_ROOT=${APP_DIR}"
Environment="AGENTGUARD_DASHBOARD_DIR=${APP_DIR}/dashboard/dist"
ExecStartPre=-/bin/sh -c '${OLLAMA_BIN} list >/dev/null 2>&1 && curl -fsS ${OLLAMA_HOST_URL}/api/generate -d "{\"model\":\"${AGENTGUARD_MODEL}\",\"prompt\":\"\",\"keep_alive\":\"24h\"}" >/dev/null 2>&1 || true'
ExecStart=${VENV_DIR}/bin/agentguard serve --config ${CONFIG_FILE} --port ${AGENTGUARD_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

  if systemctl --user daemon-reload >/dev/null 2>&1 && systemctl --user enable agentguard.service >/dev/null 2>&1; then
    BOOT_METHOD="systemd-user"
    if command -v loginctl >/dev/null 2>&1; then
      loginctl enable-linger "${USER:-$(id -un)}" 2>/dev/null || true
    fi
    if [[ "$START_DAEMON" == "1" ]]; then
      # Stop any manual pidfile daemon first so systemd owns the port cleanly
      "$WRAPPER" stop >/dev/null 2>&1 || true
      systemctl --user restart agentguard.service
    fi
    ok "Enabled systemd boot service: ~/.config/systemd/user/agentguard.service"
  fi
fi

# Fallback to crontab @reboot if systemd user session is unavailable (e.g. minimal VM/container)
if [[ "$BOOT_METHOD" == "daemon" ]]; then
  BOOT_SCRIPT="$AGENTGUARD_HOME/boot-start.sh"
  cat > "$BOOT_SCRIPT" <<EOF
#!/usr/bin/env bash
export PATH="\$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:\$PATH"
if ! curl -fsS "${OLLAMA_HOST_URL}/api/tags" >/dev/null 2>&1; then
  nohup "${OLLAMA_BIN}" serve >"${AGENTGUARD_HOME}/ollama.log" 2>&1 &
  sleep 3
fi
curl -fsS "${OLLAMA_HOST_URL}/api/generate" -d '{"model":"${AGENTGUARD_MODEL}","prompt":"","keep_alive":"24h"}' >/dev/null 2>&1 || true
"${WRAPPER}" serve --daemon --port "${AGENTGUARD_PORT}"
EOF
  chmod +x "$BOOT_SCRIPT"

  if command -v crontab >/dev/null 2>&1; then
    EXISTING_CRON="$(crontab -l 2>/dev/null || true)"
    FILTERED_CRON="$(printf "%s\n" "$EXISTING_CRON" | grep -v "boot-start.sh" || true)"
    printf "%s\n@reboot %s >/dev/null 2>&1\n" "$FILTERED_CRON" "$BOOT_SCRIPT" | sed '/^$/N;/^\n$/D' | crontab - 2>/dev/null && {
      BOOT_METHOD="cron-reboot"
      ok "Registered @reboot auto-start entry in crontab ($BOOT_SCRIPT)"
    } || warn "Could not write crontab entry; boot script saved at $BOOT_SCRIPT"
  else
    ok "Created boot startup script at $BOOT_SCRIPT"
  fi

  if [[ "$START_DAEMON" == "1" ]]; then
    info "Starting AgentGuard background daemon on port $AGENTGUARD_PORT..."
    "$WRAPPER" serve --daemon --port "$AGENTGUARD_PORT"
  fi
fi

# ==============================================================================
# STEP 5: END-TO-END INSTALLATION & MODEL VERIFICATION
# ==============================================================================
section "Step 5/5 · Verifying Installation, Model Inference & Firewall Health"

# 5.1 Verify Ollama API + Model presence
if curl -fsS "${OLLAMA_HOST_URL}/api/tags" | grep -q "${AGENTGUARD_MODEL%%:*}"; then
  ok "Verified Ollama registry contains '${AGENTGUARD_MODEL}'"
else
  fail "Model '${AGENTGUARD_MODEL}' was not found in Ollama registry (${OLLAMA_HOST_URL}/api/tags)."
fi

# 5.2 Warm up & verify model inference with 24h keep_alive
info "Verifying '${AGENTGUARD_MODEL}' inference response and pinning model in memory..."
if curl -fsS "${OLLAMA_HOST_URL}/api/generate" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${AGENTGUARD_MODEL}\",\"prompt\":\"Check environment health\",\"stream\":false,\"keep_alive\":\"24h\",\"options\":{\"num_predict\":8}}" >/dev/null; then
  ok "Verified live AI model inference (${AGENTGUARD_MODEL} responded & pinned with keep_alive=24h)"
else
  fail "Model '${AGENTGUARD_MODEL}' failed test inference request."
fi

# 5.3 Verify AgentGuard service health & Llama Guard connectivity
if [[ "$START_DAEMON" == "1" ]]; then
  HEALTH_JSON=""
  for _ in {1..30}; do
    if HEALTH_JSON="$(curl -fsS "http://127.0.0.1:${AGENTGUARD_PORT}/v1/healthz" 2>/dev/null)"; then
      break
    fi
    sleep 0.4
  done

  if [[ -z "$HEALTH_JSON" ]]; then
    fail "AgentGuard service did not respond at http://127.0.0.1:${AGENTGUARD_PORT}/v1/healthz"
  fi

  LLM_STATUS="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("llm_guard",""))' "$HEALTH_JSON")"
  RAG_CHUNKS="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("rag_chunks",0))' "$HEALTH_JSON")"
  MCP_SERVERS="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("mcp_servers",0))' "$HEALTH_JSON")"

  ok "Verified AgentGuard API & Dashboard at http://127.0.0.1:${AGENTGUARD_PORT}/ (status: ok)"
  ok "Verified Tier-4 Llama Guard status: ${LLM_STATUS} (${AGENTGUARD_MODEL})"
  ok "Verified Threat-RAG & MCP Hub: ${RAG_CHUNKS} contextual chunks, ${MCP_SERVERS} built MCP servers"
fi

ok "Verified boot auto-start configuration (mode: ${BOOT_METHOD})"

printf "\n${bold}${green}🎉 Setup Complete! AgentGuard + Ollama (${AGENTGUARD_MODEL}) are verified and active.${reset}\n"
printf "   • ${bold}Dashboard:${reset}      http://127.0.0.1:${AGENTGUARD_PORT}/\n"
printf "   • ${bold}AI Model:${reset}       ${AGENTGUARD_MODEL} (${OLLAMA_HOST_URL})\n"
printf "   • ${bold}Auto-Boot:${reset}      Enabled (${BOOT_METHOD})\n"
printf "   • ${bold}Check Status:${reset}   agentguard status\n"
printf "   • ${bold}Hardware Check:${reset} agentguard hwcheck\n"
printf "   • ${bold}Env Doctor:${reset}     agentguard doctor\n"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  printf "\n   ${yellow}Note:${reset} Add ~/.local/bin to your PATH if needed:\n"
  printf "   export PATH=\"\$HOME/.local/bin:\$PATH\"\n"
fi
printf "\n"
