<#
.SYNOPSIS
  Backup & restore Jarvis personal data (H12.15) — Windows / PowerShell.

.DESCRIPTION
  agents\data\ + memory_logs\ are git-ignored (local-first) and hold the ONLY
  real-data state: H8 personal memory, sessions/checkpoints, audit log,
  user-built workflows, and the ingested corpus. They are not in git and not on
  GitHub, so deleting the folder / reinstalling wipes them permanently. This
  gives you a local safety net.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\backup-data.ps1
  powershell -ExecutionPolicy Bypass -File scripts\backup-data.ps1 backup D:\Backups
  powershell -ExecutionPolicy Bypass -File scripts\backup-data.ps1 restore .\backups\jarvis-data-20260602-120000.zip
  powershell -ExecutionPolicy Bypass -File scripts\backup-data.ps1 list

  Set $env:BACKUP_DIR to override the default destination (e.g. an external/cloud drive).
#>
param(
  [string]$Action = "backup",
  [string]$Path = ""
)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$DataDirs = @("agents\data", "memory_logs") | Where-Object { Test-Path (Join-Path $Root $_) }
$Dest = if ($env:BACKUP_DIR) { $env:BACKUP_DIR } else { Join-Path $Root "backups" }
$Keep = 14

switch ($Action) {
  "backup" {
    if ($Path) { $Dest = $Path }
    if (-not $DataDirs) { Write-Host "Nothing to back up yet (no agents\data or memory_logs)."; break }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $ts  = Get-Date -Format "yyyyMMdd-HHmmss"
    $out = Join-Path $Dest "jarvis-data-$ts.zip"
    $full = $DataDirs | ForEach-Object { Join-Path $Root $_ }
    Compress-Archive -Path $full -DestinationPath $out -Force
    Write-Host "OK Backup created: $out"
    # Retention: keep the most recent $Keep.
    Get-ChildItem -Path $Dest -Filter "jarvis-data-*.zip" |
      Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep |
      Remove-Item -Force -ErrorAction SilentlyContinue
  }
  "restore" {
    if (-not (Test-Path $Path)) { Write-Host "Usage: backup-data.ps1 restore <archive.zip>"; exit 1 }
    Write-Host "About to restore '$Path' into $Root"
    Write-Host "This OVERWRITES current agents\data\ and memory_logs\."
    $ans = Read-Host "Continue? [y/N]"
    if ($ans -ne "y" -and $ans -ne "Y") { Write-Host "Aborted."; exit 1 }
    Expand-Archive -Path $Path -DestinationPath $Root -Force
    Write-Host "OK Restored from $Path"
  }
  "list" {
    $items = Get-ChildItem -Path $Dest -Filter "jarvis-data-*.zip" -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending
    if ($items) { $items | Select-Object Name, LastWriteTime, Length } else { Write-Host "No backups in $Dest" }
  }
  default { Write-Host "Usage: backup-data.ps1 [backup [dir] | restore <archive.zip> | list]" }
}
