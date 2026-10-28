<#
.SYNOPSIS
    Jarvis Hub — complete installer (Windows, PowerShell).
.DESCRIPTION
    Sets up everything from one script:
      JARVIS:    Python 3.12 venv + dependencies (requirements-beta.txt) + tests
    (INSTALL.bat is the double-click equivalent; this is the PowerShell path.)
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Nerva — install (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---- 1. Python 3.12+ ----
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[FAIL] Python not found. Install Python 3.12+ (add to PATH) and re-run." -ForegroundColor Red
    Write-Host "       https://www.python.org/downloads/"
    exit 1
}
$ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[1/4] Python $ver" -ForegroundColor Green

# ---- 2. venv + JARVIS dependencies ----
Write-Host "[2/4] Creating .venv and installing JARVIS dependencies..." -ForegroundColor Yellow
$venvPath = Join-Path $Root ".venv"
if (-not (Test-Path $venvPath)) { & python -m venv $venvPath }
$vpy = Join-Path $venvPath "Scripts" "python.exe"
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r requirements-beta.txt
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] dependency install failed" -ForegroundColor Red; exit 1 }
Write-Host "      dependencies installed." -ForegroundColor Green

# ---- 3. Verify JARVIS with the offline test suite ----
Write-Host "[3/4] Running the JARVIS offline test suite..." -ForegroundColor Yellow
& $vpy -m pytest -q
$testsOk = ($LASTEXITCODE -eq 0)

# ---- 4. Done ----
Write-Host "[4/4] Done." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
if (-not $testsOk) { Write-Host "  (some tests failed — you can still try START.bat)" -ForegroundColor Yellow }
Write-Host "  Start everything:    START.bat        (Nerva :8080)"
Write-Host "  Open  http://127.0.0.1:8080/   (V2 cockpit; legacy HUD at /v1)"
Write-Host "============================================================" -ForegroundColor Cyan
