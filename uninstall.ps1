# AgentGuard Windows Clean Uninstaller
[CmdletBinding()]
param(
    [switch]$Yes = $false,
    [switch]$KeepData = $false,
    [switch]$PurgeModel = $false
)

$ErrorActionPreference = "Continue"

$AgentGuardHome = if ($env:AGENTGUARD_HOME) { $env:AGENTGUARD_HOME } else { "$env:USERPROFILE\.agentguard" }
$LocalApp = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { "$env:USERPROFILE\AppData\Local" }
$BinDir = "$LocalApp\AgentGuard\bin"
$WrapperCmd = "$BinDir\agentguard.cmd"

function Write-Info($msg) { Write-Host "[agentguard] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[agentguard] √ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[agentguard] ! $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  AgentGuard Windows Uninstaller" -ForegroundColor White
Write-Host ""

if (-not $Yes) {
    Write-Host "This will remove:"
    Write-Host "  * AgentGuard daemon and scheduled tasks"
    Write-Host "  * Claude Code, Codex CLI, and OpenCode hooks"
    Write-Host "  * AgentGuard installation directory ($AgentGuardHome)"
    if ($KeepData) {
        Write-Host "  (Preserving $AgentGuardHome\events.db)" -ForegroundColor Green
    }
    Write-Host ""
    $resp = Read-Host "Are you sure you want to proceed? [y/N]"
    if ($resp.Trim().ToLower() -notin @("y", "yes")) {
        Write-Info "Uninstallation cancelled."
        exit 0
    }
}

# 1. Stop daemon & unregister hooks via CLI if available
$VenvPy = "$AgentGuardHome\venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    Write-Info "Stopping daemon and unregistering hooks..."
    $cliArgs = @("-m", "agentguard.cli", "uninstall", "-y")
    if ($KeepData) { $cliArgs += "--keep-data" }
    & $VenvPy $cliArgs 2>$null
} else {
    # Fallback manual task delete
    schtasks /Delete /TN "AgentGuard" /F 2>$null
}

# 2. Remove Task Scheduler task & HKCU Run key
Write-Info "Cleaning up auto-start registrations..."
schtasks /Delete /TN "AgentGuard" /F 2>$null
try {
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "AgentGuard" -ErrorAction SilentlyContinue
} catch {}

# 3. Remove wrapper from BinDir
if (Test-Path $WrapperCmd) {
    Remove-Item -Force $WrapperCmd -ErrorAction SilentlyContinue
    Write-Ok "Removed CLI wrapper: $WrapperCmd"
}

# 4. Remove User PATH entry if empty
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -like "*$BinDir*") {
    $NewPath = ($UserPath.Split(";") | Where-Object { $_ -ne $BinDir -and $_ -ne "" }) -join ";"
    [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Ok "Removed $BinDir from User PATH."
}

# 5. Purge Ollama model if requested
if ($PurgeModel) {
    $ollamaBin = Get-Command "ollama" -ErrorAction SilentlyContinue
    if ($ollamaBin) {
        Write-Info "Removing llama-guard3:1b model from Ollama..."
        & ollama rm "llama-guard3:1b" 2>$null
        Write-Ok "Removed llama-guard3:1b from Ollama."
    }
}

# 6. Clean data dir
if (Test-Path $AgentGuardHome) {
    if ($KeepData) {
        Get-ChildItem -Path $AgentGuardHome -Exclude "events.db" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "Removed application files (kept $AgentGuardHome\events.db)"
    } else {
        Remove-Item -Recurse -Force $AgentGuardHome -ErrorAction SilentlyContinue
        Write-Ok "Removed $AgentGuardHome"
    }
}

Write-Host ""
Write-Ok "AgentGuard uninstalled successfully."
