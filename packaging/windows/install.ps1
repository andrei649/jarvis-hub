# install.ps1 — install the built Nerva onedir bundle on Windows.
#
# Run AFTER building on this machine (see docs/PACKAGING.md):
#   python scripts\build_exe.py
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 [-Launch] [-NoBrowser]
#
# (From a source checkout use INSTALL.bat instead — it runs scripts\bootstrap.py.)
#
# What it does (no admin rights needed):
#   1. Copies dist\nerva  ->  %LOCALAPPDATA%\Programs\Nerva
#   2. Creates a Start Menu shortcut ("Nerva")
#   3. Reminds where the personal data folder lives (Documents\Nerva —
#      created by Nerva itself on first run; never touched by this script)
#   4. With -Launch: starts nerva.exe and opens the Command Center
#      (http://127.0.0.1:8080/v2) once /readyz answers — the install ends
#      inside the product, loopback only. -NoBrowser skips the browser.
#
# Uninstall = delete %LOCALAPPDATA%\Programs\Nerva and the shortcut.
# Documents\Nerva (memory, .env, skills, souls) is yours and is kept.

param(
    [switch]$Launch,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$repoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$distDir    = Join-Path $repoRoot "dist\nerva"
$installDir = Join-Path $env:LOCALAPPDATA "Programs\Nerva"
$exePath    = Join-Path $installDir "nerva.exe"

if (-not (Test-Path (Join-Path $distDir "nerva.exe"))) {
    Write-Error "dist\nerva\nerva.exe not found - build first: python scripts\build_exe.py"
}

Write-Host "Installing to $installDir ..."
if (Test-Path $installDir) {
    # Upgrade in place: replace the app folder. Personal data is elsewhere
    # (Documents\Nerva), so this is always safe.
    Remove-Item -Recurse -Force $installDir
}
New-Item -ItemType Directory -Force -Path (Split-Path $installDir) | Out-Null
Copy-Item -Recurse -Force $distDir $installDir

$startMenu = [Environment]::GetFolderPath("Programs")
$shortcut  = Join-Path $startMenu "Nerva.lnk"
$shell     = New-Object -ComObject WScript.Shell
$lnk       = $shell.CreateShortcut($shortcut)
$lnk.TargetPath       = $exePath
$lnk.WorkingDirectory = $installDir
$lnk.Description      = "Nerva - local-first personal AI OS"
$lnk.Save()

Write-Host ""
Write-Host "Installed:  $exePath"
Write-Host "Shortcut:   $shortcut"
Write-Host "Your data:  $([Environment]::GetFolderPath('MyDocuments'))\Nerva  (created on first run)"
Write-Host ""
Write-Host "Start Nerva from the Start Menu, then open http://127.0.0.1:8080/v2  (loopback only;"
Write-Host "a phone or second device is a token-gated decision: docs\PHONE_ACCESS.md)"

if ($Launch) {
    Write-Host ""
    Write-Host "Starting Nerva..."
    Start-Process -FilePath $exePath -WorkingDirectory $installDir
    if (-not $NoBrowser) {
        $ready = $false
        for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
            try {
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:8080/readyz" -UseBasicParsing -TimeoutSec 2
                if ($r.StatusCode -eq 200) { $ready = $true }
            } catch { Start-Sleep -Seconds 2 }
        }
        if ($ready) {
            Start-Process "http://127.0.0.1:8080/v2"
        } else {
            Write-Warning "Nerva did not answer /readyz within ~2 minutes - open http://127.0.0.1:8080/v2 manually or check the nerva.exe window."
        }
    }
}
