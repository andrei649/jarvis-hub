<#
.SYNOPSIS
    Jarvis Hub — complete installer (Windows, PowerShell).
.DESCRIPTION
    Sets up everything from one script:
      JARVIS:    Python 3.12 venv + dependencies (requirements-beta.txt) + tests
      WorldView: Node 20+ check, .env scaffolding, npm install (4D OSINT stack)
    Soft-skips WorldView if Node/Docker are absent so JARVIS still installs.
    (INSTALL.bat is the double-click equivalent; this is the PowerShell path.)
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  JARVIS HUB + WorldView — install (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ---- 1. Python 3.12+ ----
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[FAIL] Python not found. Install Python 3.12+ (add to PATH) and re-run." -ForegroundColor Red
    Write-Host "       https://www.python.org/downloads/"
    exit 1
}
$ver = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Host "[1/5] Python $ver" -ForegroundColor Green

# ---- 2. venv + JARVIS dependencies ----
Write-Host "[2/5] Creating .venv and installing JARVIS dependencies..." -ForegroundColor Yellow
$venvPath = Join-Path $Root ".venv"
if (-not (Test-Path $venvPath)) { & python -m venv $venvPath }
$vpy = Join-Path $venvPath "Scripts" "python.exe"
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r requirements-beta.txt
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] dependency install failed" -ForegroundColor Red; exit 1 }
Write-Host "      dependencies installed." -ForegroundColor Green

# ---- 3. WorldView (4D OSINT) — optional, soft-skip if tooling absent ----
Write-Host "[3/5] WorldView setup (optional)..." -ForegroundColor Yellow
if (Test-Path (Join-Path $Root "worldview" "package.json")) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm  = Get-Command npm  -ErrorAction SilentlyContinue
    if ($node -and $npm) {
        $nodeMajor = (& node -p "process.versions.node.split('.')[0]")
        if ([int]$nodeMajor -lt 20) {
            Write-Host "      [WARN] Node $(& node -v) is < 20 — WorldView needs Node 20+. Skipping npm install." -ForegroundColor Yellow
        } else {
            foreach ($pair in @(
                @("worldview\.env.example",                 "worldview\.env"),
                @("worldview\backend-api\.env.example",      "worldview\backend-api\.env"),
                @("worldview\frontend\.env.local.example",   "worldview\frontend\.env.local"))) {
                if ((Test-Path $pair[0]) -and (-not (Test-Path $pair[1]))) { Copy-Item $pair[0] $pair[1] }
            }
            Write-Host "      .env files ready; installing Node deps (a few minutes the first time)..." -ForegroundColor Yellow
            Push-Location (Join-Path $Root "worldview")
            & npm install
            if ($LASTEXITCODE -ne 0) { Write-Host "      [WARN] npm install reported errors." -ForegroundColor Yellow }
            Pop-Location
            Write-Host "      WorldView ready." -ForegroundColor Green
        }
    } else {
        Write-Host "      [SKIP] Node/npm not found (need Node 20+) — WorldView not set up. JARVIS works without it." -ForegroundColor Yellow
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "      [NOTE] Docker not found — WorldView infra needs it; install Docker Desktop to run WorldView." -ForegroundColor Yellow
    }
} else {
    Write-Host "      [SKIP] worldview/ not present in this checkout." -ForegroundColor Yellow
}

# ---- 4. Verify JARVIS with the offline test suite ----
Write-Host "[4/5] Running the JARVIS offline test suite..." -ForegroundColor Yellow
& $vpy -m pytest -q
$testsOk = ($LASTEXITCODE -eq 0)

# ---- 5. Done ----
Write-Host "[5/5] Done." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
if (-not $testsOk) { Write-Host "  (some tests failed — you can still try START.bat)" -ForegroundColor Yellow }
Write-Host "  Start everything:    START.bat        (JARVIS :8080 + WorldView :3000)"
Write-Host "  JARVIS only:         set JARVIS_WORLDVIEW=0  then START.bat"
Write-Host "  WorldView demo data: cd worldview; npm run db:seed"
Write-Host "  Open  http://127.0.0.1:8080/   (V2 cockpit; legacy HUD at /v1)"
Write-Host "============================================================" -ForegroundColor Cyan
