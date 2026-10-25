# AgentGuard Windows Installer & Hardware-Verified Local AI Bootstrapper
# Compatible with Windows PowerShell 5.1 and PowerShell 7+
[CmdletBinding()]
param(
    [string]$Model = $env:AGENTGUARD_MODEL,
    [switch]$Lightweight = ($env:AGENTGUARD_LIGHTWEIGHT -eq "1"),
    [switch]$Yes = ($env:AGENTGUARD_ASSUME_YES -eq "1"),
    [switch]$NoStart = ($env:AGENTGUARD_NO_START -eq "1"),
    [switch]$HwCheckOnly = $false,
    [string]$Port = $env:AGENTGUARD_PORT,
    [string]$RepoUrl = $env:AGENTGUARD_REPO_URL,
    [string]$Branch = $env:AGENTGUARD_BRANCH
)

$ErrorActionPreference = "Stop"

if (-not $Model) { $Model = "llama-guard3:1b" }
if (-not $Port) { $Port = "8907" }
if (-not $RepoUrl) { $RepoUrl = "https://github.com/Sajib023/AgentGuard.git" }
if (-not $Branch) { $Branch = "master" }

$AgentGuardHome = if ($env:AGENTGUARD_HOME) { $env:AGENTGUARD_HOME } else { "$env:USERPROFILE\.agentguard" }
$LocalApp = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { "$env:USERPROFILE\AppData\Local" }
$BinDir = "$LocalApp\AgentGuard\bin"
$VenvDir = "$AgentGuardHome\venv"
$AppDir = "$AgentGuardHome\app"
$ConfigFile = "$AgentGuardHome\agentguard.yaml"
$OllamaHostUrl = if ($env:OLLAMA_HOST_URL) { $env:OLLAMA_HOST_URL } else { "http://127.0.0.1:11434" }

function Write-Info($msg) { Write-Host "[agentguard] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[agentguard] √ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[agentguard] ! $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "[agentguard] X $msg" -ForegroundColor Red; exit 1 }
function Write-Section($msg) {
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkGray
    Write-Host "  $msg" -ForegroundColor White
    Write-Host ("=" * 78) -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  AgentGuard Windows Setup & Hardware-Verified Local AI Installer" -ForegroundColor White
Write-Host "  Local-First Runtime Firewall * Threat-RAG & GraphRAG * Circuit Breaker * MCP Hub" -ForegroundColor DarkGray

# ------------------------------------------------------------------------------
# 0. Find Python 3.11+
# ------------------------------------------------------------------------------
$PythonBin = ""
$Candidates = @("py -3.12", "py -3.11", "py -3", "python")
foreach ($cand in $Candidates) {
    try {
        $parts = $cand.Split(" ")
        $exe = $parts[0]
        $args = if ($parts.Length -gt 1) { $parts[1..($parts.Length - 1)] } else { @() }
        $ver = & $exe $args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $major, $minor = $ver.Trim().Split(".")
            if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                $actualPath = & $exe $args -c "import sys; print(sys.executable)" 2>$null
                # Avoid Microsoft Store execution alias stub that opens the store if not installed
                if ($actualPath -notlike "*WindowsApps*") {
                    $PythonBin = $actualPath.Trim()
                    break
                }
            }
        }
    } catch {}
}

if (-not $PythonBin) {
    Write-Warn "Python 3.11+ was not found on your system."
    Write-Info "Installing Python 3.12 via winget..."
    try {
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $PythonBin = (Get-Command "python" -ErrorAction SilentlyContinue).Source
    } catch {}
    if (-not $PythonBin) {
        Write-Fail "Python 3.11+ is required. Please install Python 3.11+ from https://www.python.org/downloads/ and re-run."
    }
}
Write-Ok "Found Python: $PythonBin"

# ------------------------------------------------------------------------------
# STEP 1: Hardware Compatibility Check
# ------------------------------------------------------------------------------
Write-Section "Step 1/5: Hardware Compatibility Check (Selected Model: $Model)"

# Query Windows Hardware
$TotalRamBytes = 0
$AvailRamBytes = 0
try {
    $osInfo = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
    if ($osInfo) {
        $TotalRamBytes = [int64]$osInfo.TotalVisibleMemorySize * 1024
        $AvailRamBytes = [int64]$osInfo.FreePhysicalMemory * 1024
    }
} catch {}

$CpuCores = [System.Environment]::ProcessorCount
$Drive = Get-PSDrive -Name ($AgentGuardHome.Substring(0, 1)) -ErrorAction SilentlyContinue
$FreeDiskBytes = if ($Drive) { $Drive.Free } else { 0 }

$TotalRamMB = [math]::Round($TotalRamBytes / 1MB)
$AvailRamMB = [math]::Round($AvailRamBytes / 1MB)
$FreeDiskMB = [math]::Round($FreeDiskBytes / 1MB)

$MinRamMB = if ($env:AGENTGUARD_MIN_RAM_MB) { [int]$env:AGENTGUARD_MIN_RAM_MB } else { 3584 }
$MinAvailMB = if ($env:AGENTGUARD_MIN_AVAIL_RAM_MB) { [int]$env:AGENTGUARD_MIN_AVAIL_RAM_MB } else { 1024 }
$MinDiskMB = if ($env:AGENTGUARD_MIN_DISK_MB) { [int]$env:AGENTGUARD_MIN_DISK_MB } else { 5120 }
$MinCores = if ($env:AGENTGUARD_MIN_CPU_CORES) { [int]$env:AGENTGUARD_MIN_CPU_CORES } else { 2 }

$CpuPass = ($CpuCores -ge $MinCores)
$RamPass = ($TotalRamMB -ge $MinRamMB -and $AvailRamMB -ge $MinAvailMB)
$DiskPass = ($FreeDiskMB -ge $MinDiskMB)
$Compatible = ($CpuPass -and $RamPass -and $DiskPass)

Write-Host ("  CPU:     [{0}] {1} Cores | Required: >= {2} cores" -f $(if ($CpuPass) {"PASS"} else {"FAIL"}), $CpuCores, $MinCores)
Write-Host ("  RAM:     [{0}] {1:N1} GB total, {2:N1} GB available | Required: >= {3:N1} GB total, >= {4:N1} GB avail" -f $(if ($RamPass) {"PASS"} else {"FAIL"}), ($TotalRamMB / 1024), ($AvailRamMB / 1024), ($MinRamMB / 1024), ($MinAvailMB / 1024))
Write-Host ("  Storage: [{0}] {1:N1} GB free | Required: >= {2:N1} GB free" -f $(if ($DiskPass) {"PASS"} else {"FAIL"}), ($FreeDiskMB / 1024), ($MinDiskMB / 1024))

if ($HwCheckOnly) {
    if ($Compatible) { Write-Ok "Hardware is compatible."; exit 0 }
    else { Write-Warn "Hardware is incompatible."; exit 1 }
}

# ------------------------------------------------------------------------------
# STEP 2: Permission & Lightweight Fallback
# ------------------------------------------------------------------------------
Write-Section "Step 2/5: Installation Mode & Confirmation"

$InstallMode = "Full"
if (-not $Compatible -or $Lightweight) {
    $InstallMode = "Lightweight"
    Write-Warn "Running in Lightweight Mode (Tiers 1-3.5 deterministic regex, heuristics, Contextual RAG, GraphRAG lineage, Circuit Breaker, and Dashboard)."
} else {
    Write-Ok "Hardware verification passed. Full Mode with local AI model ($Model) available."
}

if (-not $Yes) {
    $resp = Read-Host "Proceed with AgentGuard installation ($InstallMode Mode)? [y/N]"
    if ($resp.Trim().ToLower() -notin @("y", "yes")) {
        Write-Info "Installation cancelled by user."
        exit 0
    }
}

# ------------------------------------------------------------------------------
# STEP 3: Ollama Runtime (Full AI Mode only)
# ------------------------------------------------------------------------------
if ($InstallMode -eq "Full") {
    Write-Section "Step 3/5: Ollama Runtime & Model Setup"
    $OllamaBin = Get-Command "ollama" -ErrorAction SilentlyContinue
    if (-not $OllamaBin) {
        Write-Info "Ollama not found. Installing Ollama for Windows..."
        $installed = $false
        try {
            winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
            $installed = $true
        } catch {}
        if (-not $installed) {
            Write-Info "Downloading OllamaSetup.exe directly..."
            $setupExe = "$env:TEMP\OllamaSetup.exe"
            Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setupExe
            Start-Process -FilePath $setupExe -ArgumentList "/silent" -Wait
            Remove-Item -Force $setupExe -ErrorAction SilentlyContinue
        }
        # Refresh Path
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        $OllamaBin = Get-Command "ollama" -ErrorAction SilentlyContinue
    }
    if ($OllamaBin) {
        Write-Ok "Ollama available: $($OllamaBin.Source)"
        Write-Info "Pulling model $Model (this may take a few minutes)..."
        & ollama pull $Model
        Write-Ok "Model $Model is ready."
    } else {
        Write-Warn "Ollama installation could not be completed automatically. Downgrading to Lightweight Mode."
        $InstallMode = "Lightweight"
    }
} else {
    Write-Section "Step 3/5: Skipping Ollama (Lightweight Mode)"
    Write-Info "Deterministic rules, Threat-RAG, ColBERT reranker, and GraphRAG lineage will run locally without LLM inference."
}

# ------------------------------------------------------------------------------
# STEP 4: Install AgentGuard Core & Cloudflared
# ------------------------------------------------------------------------------
Write-Section "Step 4/5: Installing AgentGuard & Tools"

New-Item -ItemType Directory -Force -Path $AgentGuardHome | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

# 4.1 Clone or copy repo
$CurrentDir = $PSScriptRoot
if (-not $CurrentDir -or -not (Test-Path "$CurrentDir\core")) {
    $CurrentDir = (Get-Location).Path
}

if (Test-Path "$CurrentDir\core") {
    Write-Info "Installing from local checkout ($CurrentDir)..."
    $AppSource = $CurrentDir
} else {
    $GitBin = Get-Command "git" -ErrorAction SilentlyContinue
    if (-not $GitBin) {
        # Check standard Git install locations on Windows
        $StandardGit = @(
            "$env:ProgramFiles\Git\cmd\git.exe",
            "${env:ProgramFiles(x86)}\Git\cmd\git.exe",
            "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"
        )
        foreach ($gp in $StandardGit) {
            if (Test-Path $gp) {
                $GitBin = @{ Source = $gp }
                $env:Path = "$env:Path;" + (Split-Path $gp)
                break
            }
        }
    }

    if (-not $GitBin) {
        Write-Info "Git not detected in PATH. Attempting to install Git via winget..."
        try {
            winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements --silent
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
            $GitBin = Get-Command "git" -ErrorAction SilentlyContinue
        } catch {}
    }

    if ($GitBin) {
        Write-Info "Cloning repository $RepoUrl ($Branch) into $AppDir..."
        if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
        & $GitBin.Source clone --depth 1 -b $Branch $RepoUrl $AppDir
        $AppSource = $AppDir
    } else {
        Write-Info "Git unavailable. Downloading repository archive directly from GitHub..."
        if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }
        New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
        
        $cleanRepo = $RepoUrl.TrimEnd("/").TrimEnd(".git")
        $zipUrl = "$cleanRepo/archive/refs/heads/$Branch.zip"
        $zipFile = "$env:TEMP\agentguard-$Branch.zip"
        $extractDir = "$env:TEMP\agentguard-extract"

        if (Test-Path $extractDir) { Remove-Item -Recurse -Force $extractDir }
        Write-Info "Downloading archive: $zipUrl..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing
            Write-Info "Extracting archive into $AppDir..."
            Expand-Archive -Path $zipFile -DestinationPath $extractDir -Force
            
            $extractedRoot = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
            if ($extractedRoot) {
                Copy-Item -Path "$($extractedRoot.FullName)\*" -Destination $AppDir -Recurse -Force
            }
            Write-Ok "Repository archive extracted successfully."
        } catch {
            Write-Fail "Failed to download repository archive: $_"
        } finally {
            Remove-Item -Force $zipFile -ErrorAction SilentlyContinue
            Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
        }
        $AppSource = $AppDir
    }
}

# 4.2 Python virtual environment
Write-Info "Creating virtual environment in $VenvDir..."
& $PythonBin -m venv $VenvDir
$VenvPy = "$VenvDir\Scripts\python.exe"

Write-Info "Installing AgentGuard core into virtual environment..."
& $VenvPy -m pip install --upgrade pip --quiet
& $VenvPy -m pip install -e "$AppSource\core" --quiet
Write-Ok "AgentGuard core installed."

# 4.3 Cloudflared for Windows
$CfExe = Get-Command "cloudflared" -ErrorAction SilentlyContinue
if (-not $CfExe) {
    $TargetCf = "$BinDir\cloudflared.exe"
    if (Test-Path $TargetCf) {
        Write-Ok "cloudflared found in $TargetCf"
    } else {
        Write-Info "Downloading cloudflared for Windows (AMD64)..."
        try {
            Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $TargetCf
            Write-Ok "cloudflared installed to $TargetCf"
        } catch {
            Write-Warn "Could not download cloudflared. Dashboard will remain local-only."
        }
    }
} else {
    Write-Ok "cloudflared found: $($CfExe.Source)"
}

# 4.4 Configuration file
$LlmGuardEnabled = if ($InstallMode -eq "Full") { "true" } else { "false" }
if (-not (Test-Path $ConfigFile)) {
    $ConfigYaml = @"
server:
  host: 127.0.0.1
  port: $Port
  db_path: "$($AgentGuardHome.Replace('\', '/'))/events.db"

firewall:
  enabled: true
  observe_mode: false
  llm_guard:
    enabled: $LlmGuardEnabled
    provider: ollama
    model: "$Model"
    endpoint: "$OllamaHostUrl"
    timeout_seconds: 20.0
    on_failure: allow_pass

dashboard:
  dir: "$($AppSource.Replace('\', '/'))/dashboard/dist"

tunnel:
  enabled: true
  cloudflared_path: ""
  extra_args: []

auth:
  enabled: true
  code_length: 8
  max_attempts: 5
  lockout_seconds: 30.0
"@
    Set-Content -Path $ConfigFile -Value $ConfigYaml -Encoding UTF8
    Write-Ok "Created configuration at $ConfigFile"
}

# 4.5 Place CMD wrapper
$WrapperCmd = "$BinDir\agentguard.cmd"
$WrapperContent = @"
@echo off
setlocal
if not defined AGENTGUARD_HOME set "AGENTGUARD_HOME=$AgentGuardHome"
if not defined AGENTGUARD_CONFIG set "AGENTGUARD_CONFIG=$ConfigFile"
if not defined AGENTGUARD_REPO_ROOT set "AGENTGUARD_REPO_ROOT=$AppSource"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
"$VenvDir\Scripts\python.exe" -m agentguard.cli %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path $WrapperCmd -Value $WrapperContent -Encoding ASCII
Write-Ok "Created CLI wrapper at $WrapperCmd"

# Add BinDir to User PATH if not present
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$BinDir*") {
    [System.Environment]::SetEnvironmentVariable("Path", "$UserPath;$BinDir", "User")
    $env:Path = "$env:Path;$BinDir"
    Write-Ok "Added $BinDir to User PATH."
}

# 4.6 Configure Agent Hooks (OpenCode, Claude, Codex)
Write-Info "Configuring agent hooks..."
& "$VenvDir\Scripts\python.exe" -m agentguard.cli setup --config $ConfigFile

# 4.7 Configure Auto-start on boot (Windows Task Scheduler)
Write-Info "Configuring Windows Task Scheduler auto-start..."
& "$VenvDir\Scripts\python.exe" -m agentguard.cli autostart enable --config $ConfigFile --port $Port --model $(if ($InstallMode -eq "Full") { $Model } else { "" })

# ------------------------------------------------------------------------------
# STEP 5: Verification & Launch
# ------------------------------------------------------------------------------
Write-Section "Step 5/5: Service Verification"

$TunnelUrl = ""
$AccessCode = ""

if (-not $NoStart) {
    Write-Info "Starting AgentGuard daemon on port $Port..."
    & "$VenvDir\Scripts\python.exe" -m agentguard.cli serve --daemon --config $ConfigFile
    
    # Poll for health check
    $Healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/healthz" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($resp) { $Healthy = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 400
    }

    if (-not $Healthy) {
        Write-Warn "AgentGuard service did not respond at http://127.0.0.1:$Port/v1/healthz yet."
    } else {
        Write-Ok "AgentGuard service is active and healthy."
    }

    # Wait up to 20 seconds for cloudflared to publish tunnel URL
    Write-Info "Waiting for Cloudflare Quick Tunnel and access code..."
    $TunnelFile = "$AgentGuardHome\tunnel_url"
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-Path $TunnelFile) {
            $val = (Get-Content -Path $TunnelFile -ErrorAction SilentlyContinue | Select-Object -First 1)
            if ($val -and $val.Trim()) { $TunnelUrl = $val.Trim(); break }
        }
        Start-Sleep -Milliseconds 500
    }

    $CodeFile = "$AgentGuardHome\access_code"
    if (Test-Path $CodeFile) {
        $rawCode = (Get-Content -Path $CodeFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($rawCode) { $AccessCode = $rawCode.Trim() }
    }
} else {
    Write-Info "Service start skipped (--no-start). Run 'agentguard serve --daemon' to start."
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Green
Write-Host "  AgentGuard Runtime Security Firewall is active" -ForegroundColor Green
Write-Host "  * Dashboard (Local):        http://127.0.0.1:$Port/" -ForegroundColor White
if ($AccessCode) {
    $half = [math]::Max(1, [math]::Floor($AccessCode.Length / 2))
    $displayCode = "$($AccessCode.Substring(0, $half))-$($AccessCode.Substring($half))"
    Write-Host "  * Access Code:              $displayCode  (required for remote access)" -ForegroundColor Yellow
}
if ($TunnelUrl) {
    Write-Host "  * Cloudflare Quick Tunnel:  $TunnelUrl" -ForegroundColor Cyan
} else {
    Write-Host "  * Cloudflare Quick Tunnel:  Awaiting tunnel... (run 'agentguard status' in a few seconds)" -ForegroundColor DarkGray
}
Write-Host "  * Service Logs:             $AgentGuardHome\agentguard.log" -ForegroundColor DarkGray
Write-Host "  * CLI Commands:             agentguard status | agentguard doctor | agentguard stop" -ForegroundColor White
Write-Host "==============================================================================" -ForegroundColor Green
