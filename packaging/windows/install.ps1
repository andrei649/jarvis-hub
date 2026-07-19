# install.ps1 — install the built Jarvis onedir bundle on Windows.
#
# Run AFTER building on this machine (see docs/PACKAGING.md):
#   python scripts\build_exe.py
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
#
# What it does (no admin rights needed):
#   1. Copies dist\jarvis  ->  %LOCALAPPDATA%\Programs\Jarvis
#   2. Creates a Start Menu shortcut ("Jarvis")
#   3. Reminds where the personal data folder lives (Documents\Jarvis —
#      created by Jarvis itself on first run; never touched by this script)
#
# Uninstall = delete %LOCALAPPDATA%\Programs\Jarvis and the shortcut.
# Documents\Jarvis (memory, .env, skills, souls) is yours and is kept.

$ErrorActionPreference = "Stop"

$repoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$distDir    = Join-Path $repoRoot "dist\jarvis"
$installDir = Join-Path $env:LOCALAPPDATA "Programs\Jarvis"
$exePath    = Join-Path $installDir "jarvis.exe"

if (-not (Test-Path (Join-Path $distDir "jarvis.exe"))) {
    Write-Error "dist\jarvis\jarvis.exe not found - build first: python scripts\build_exe.py"
}

Write-Host "Installing to $installDir ..."
if (Test-Path $installDir) {
    # Upgrade in place: replace the app folder. Personal data is elsewhere
    # (Documents\Jarvis), so this is always safe.
    Remove-Item -Recurse -Force $installDir
}
New-Item -ItemType Directory -Force -Path (Split-Path $installDir) | Out-Null
Copy-Item -Recurse -Force $distDir $installDir

$startMenu = [Environment]::GetFolderPath("Programs")
$shortcut  = Join-Path $startMenu "Jarvis.lnk"
$shell     = New-Object -ComObject WScript.Shell
$lnk       = $shell.CreateShortcut($shortcut)
$lnk.TargetPath       = $exePath
$lnk.WorkingDirectory = $installDir
$lnk.Description      = "Jarvis Hub - local-first personal AI"
$lnk.Save()

Write-Host ""
Write-Host "Installed:  $exePath"
Write-Host "Shortcut:   $shortcut"
Write-Host "Your data:  $([Environment]::GetFolderPath('MyDocuments'))\Jarvis  (created on first run)"
Write-Host ""
Write-Host "Start Jarvis from the Start Menu, then open http://127.0.0.1:8080/"
