# install.ps1 — install the built Nerva onedir bundle on Windows.
#
# Run AFTER building on this machine (see docs/PACKAGING.md):
#   python scripts\build_exe.py
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
#
# What it does (no admin rights needed):
#   1. Copies dist\nerva  ->  %LOCALAPPDATA%\Programs\Nerva
#   2. Creates a Start Menu shortcut ("Nerva")
#   3. Reminds where the personal data folder lives (Documents\Nerva —
#      created by Nerva itself on first run; never touched by this script)
#
# Uninstall = delete %LOCALAPPDATA%\Programs\Nerva and the shortcut.
# Documents\Nerva (memory, .env, skills, souls) is yours and is kept.

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
Write-Host "Start Nerva from the Start Menu, then open http://127.0.0.1:8080/"
