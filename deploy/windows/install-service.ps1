<#
.SYNOPSIS
    Install/uninstall Jarvis Hub as a Windows service via NSSM. (H23.15)

.DESCRIPTION
    Windows has no native "run this script as a resilient service" primitive, so
    we use NSSM (the Non-Sucking Service Manager, https://nssm.cc) — the standard
    way to host a console app as a service. NSSM restarts on crash and stops the
    service by sending Ctrl-C to the console (AppStopMethodConsole), which reaches
    Python as SIGINT → uvicorn drains in-flight requests within
    JARVIS_SHUTDOWN_TIMEOUT, then exits (graceful shutdown, H23.11).

.PARAMETER InstallRoot
    The Jarvis checkout (contains serve.py and .venv\). Default: this repo root.

.PARAMETER DataRoot
    JARVIS_HOME — where runtime state (DBs, tokens, logs) lives. Must be writable.

.PARAMETER Uninstall
    Remove the service instead of installing it.

.EXAMPLE
    # from an elevated PowerShell, in the repo root:
    .\deploy\windows\install-service.ps1 -InstallRoot C:\jarvis-hub -DataRoot C:\ProgramData\jarvis-hub

.EXAMPLE
    .\deploy\windows\install-service.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$ServiceName = "JarvisHub",
    [string]$InstallRoot = (Resolve-Path "$PSScriptRoot\..\.." ).Path,
    [string]$DataRoot    = "$env:ProgramData\jarvis-hub",
    [string]$BindHost    = "127.0.0.1",
    [int]   $Port        = 8080,
    [int]   $ShutdownTimeout = 10,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$nssm = (Get-Command nssm -ErrorAction SilentlyContinue)?.Source
if (-not $nssm) {
    Write-Error @"
NSSM not found on PATH. Install it first (it's a single .exe):
  winget install NSSM            # or: choco install nssm
  # or download from https://nssm.cc/download and put nssm.exe on PATH
Then re-run this script from an elevated PowerShell.
"@
    exit 1
}

if ($Uninstall) {
    & $nssm stop   $ServiceName
    & $nssm remove $ServiceName confirm
    Write-Host "Removed service '$ServiceName'."
    exit 0
}

$python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$serve  = Join-Path $InstallRoot "serve.py"
if (-not (Test-Path $python)) { Write-Error "venv python not found: $python  (run install first)"; exit 1 }
if (-not (Test-Path $serve))  { Write-Error "serve.py not found: $serve"; exit 1 }
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

Write-Host "Installing service '$ServiceName' → $python $serve"
& $nssm install $ServiceName $python $serve
& $nssm set $ServiceName AppDirectory $InstallRoot
& $nssm set $ServiceName Description "Jarvis Hub — personal AI cabinet (FastAPI)"
& $nssm set $ServiceName Start SERVICE_AUTO_START

# Operability env (H23.11). Loopback default; off-loopback needs a token / the
# explicit insecure-bind opt-in or serve.py refuses to boot (fail-closed).
& $nssm set $ServiceName AppEnvironmentExtra `
    "JARVIS_HOST=$BindHost" `
    "JARVIS_PORT=$Port" `
    "JARVIS_SHUTDOWN_TIMEOUT=$ShutdownTimeout" `
    "JARVIS_HOME=$DataRoot"

# Graceful stop: send Ctrl-C (→ SIGINT → uvicorn drains), give it a margin over
# the app's own shutdown timeout before NSSM force-kills.
& $nssm set $ServiceName AppStopMethodConsole ([int](($ShutdownTimeout + 5) * 1000))
# Restart on unexpected exit, with backoff so a crash-loop doesn't thrash.
& $nssm set $ServiceName AppExit Default Restart
& $nssm set $ServiceName AppRestartDelay 5000

Write-Host "Starting '$ServiceName'…"
& $nssm start $ServiceName
Write-Host "Done. Manage with: nssm status $ServiceName  |  Services.msc  |  Get-Service $ServiceName"
Write-Host "Health: curl http://${BindHost}:$Port/readyz"
