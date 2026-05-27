<#
.SYNOPSIS
    Cabinet v0.1.0 — Pure-Python Stack Installer (Windows)
.DESCRIPTION
    Installs Cabinet core dependencies, optional voice/plugin groups,
    and verifies the setup.
#>

param(
    [switch]$WithVoice,
    [switch]$WithWeb,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$CabinetRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Cabinet v0.1.0 — Stack Installer   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan

# ---- Detect Python ----
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[FAIL] Python not found. Install Python 3.11+ first." -ForegroundColor Red
    exit 1
}
$ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[OK] Python $ver found" -ForegroundColor Green

# ---- Create venv if missing ----
$venvPath = Join-Path $CabinetRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[...] Creating virtual environment..." -ForegroundColor Yellow
    & python -m venv $venvPath
    Write-Host "[OK] Virtual environment created" -ForegroundColor Green
}

# Activate
$pip = Join-Path $venvPath "Scripts" "pip.exe"
if (-not (Test-Path $pip)) {
    Write-Host "[FAIL] pip not found in venv" -ForegroundColor Red
    exit 1
}

# ---- Core dependencies ----
Write-Host "[...] Installing core dependencies..." -ForegroundColor Yellow
& $pip install --upgrade pip
& $pip install pyyaml apscheduler httpx numpy
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Core dependency install failed" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Core dependencies installed" -ForegroundColor Green

# ---- Web UI ----
if ($WithWeb -or $All) {
    Write-Host "[...] Installing web dependencies..." -ForegroundColor Yellow
    & $pip install fastapi uvicorn
    Write-Host "[OK] Web dependencies installed" -ForegroundColor Green
}

# ---- Voice pipeline ----
if ($WithVoice -or $All) {
    Write-Host "[...] Installing voice pipeline..." -ForegroundColor Yellow
    & $pip install edge-tts pygame pyaudio
    & $pip install faster-whisper torch --extra-index-url https://download.pytorch.org/whl/cu124
    & $pip install openwakeword
    Write-Host "[OK] Voice pipeline installed" -ForegroundColor Green
}

# ---- Verify ----
Write-Host "[...] Verifying installation..." -ForegroundColor Yellow
& $pip list --format=columns | Select-String -Pattern "pyyaml|apscheduler|httpx|fastapi|uvicorn|numpy|edge-tts" | ForEach-Object {
    Write-Host "  $_" -ForegroundColor Gray
}

# ---- Config check ----
$configPath = Join-Path $CabinetRoot "agents" "_system" "agents.yaml"
if (Test-Path $configPath) {
    Write-Host "[OK] Config found: $configPath" -ForegroundColor Green
} else {
    Write-Host "[WARN] Config not found at $configPath" -ForegroundColor Yellow
}

Write-Host "`n╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Cabinet ready — sir.               ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "Start with: python serve.py" -ForegroundColor White
