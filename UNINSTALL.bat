@echo off
REM ============================================================
REM  JARVIS HUB - UNINSTALL (Windows 11, double-click)
REM  Removes the installer-created software footprint: .venv\,
REM  WorldView's node_modules\ and generated .env files. Your
REM  DATA (memory_logs\ or %JARVIS_HOME%) is NOT touched unless
REM  you also pass /PURGEDATA - and even then only after you type
REM  the data folder's name back when asked.
REM
REM  Usage:  UNINSTALL.bat            (asks for confirmation)
REM          UNINSTALL.bat /DRYRUN    (print what WOULD be removed; nothing is)
REM          UNINSTALL.bat /CONFIRM   (no prompt, for scripting)
REM          UNINSTALL.bat /CONFIRM /GUI         (also remove the desktop app)
REM          UNINSTALL.bat /CONFIRM /GUIONLY     (remove ONLY the desktop app)
REM          UNINSTALL.bat /GUISUMMARY           (JSON probe of the desktop app)
REM          UNINSTALL.bat /CONFIRM /PURGEDATA   (also erase data; typed confirmation)
REM  Scripted purge: batch argument parsing splits on '=', so the
REM  non-interactive confirmation comes from an environment variable:
REM    set "NERVA_YES_PURGE=<full path of the data root>"
REM    UNINSTALL.bat /CONFIRM /PURGEDATA
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Uninstall

set "DOCONFIRM=0"
set "PURGEDATA="
set "DRYRUN="
set "GUI="
set "GUISUMMARY="
set "YESPURGE="
for %%A in (%*) do (
  if /I "%%~A"=="/CONFIRM" set "DOCONFIRM=1"
  if /I "%%~A"=="/DRYRUN" set "DRYRUN=--dry-run"
  if /I "%%~A"=="/GUI" set "GUI=--gui"
  if /I "%%~A"=="/GUIONLY" set "GUI=--gui-only"
  if /I "%%~A"=="/GUISUMMARY" set "GUISUMMARY=1"
  if /I "%%~A"=="/PURGEDATA" set "PURGEDATA=--purge-data"
  if /I "%%~A"=="/NOBACKUP" set "NOBACKUP=--no-backup"
)

echo.
echo ============================================================
echo   JARVIS HUB - UNINSTALL
echo ============================================================
echo.
echo This removes: .venv\, worldview\node_modules\, and WorldView's
echo generated .env files. Your data (memory_logs\ or %%JARVIS_HOME%%)
echo is NOT touched unless /PURGEDATA is also given.
echo.

if defined NERVA_YES_PURGE if defined PURGEDATA set "YESPURGE="--yes-purge=!NERVA_YES_PURGE!""
if defined DRYRUN set "DOCONFIRM=1"
if defined GUISUMMARY set "DOCONFIRM=1"
if "!DOCONFIRM!"=="0" (
  set /p "ANSWER=Continue? [y/N] "
  if /I not "!ANSWER!"=="y" (
    echo Cancelled.
    goto :end
  )
)

REM --- Find Python (prefer system, same reasoning as uninstall.sh: the
REM     uninstall module removes .venv\ itself) ----------------------
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (
  where python >nul 2>&1
  if %errorlevel%==0 (set "PY=python") else (
    if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (
      echo [ERROR] no Python found - cannot run the uninstall module.
      goto :end
    )
  )
)

if defined GUISUMMARY (
  "!PY!" -m agents.core.uninstall --gui-summary
  goto :end
)
if defined DRYRUN (
  "!PY!" -m agents.core.uninstall --dry-run !GUI! !PURGEDATA!
  echo.
  echo   Dry run - nothing was removed. Re-run with /CONFIRM to proceed.
  goto :end
)
"!PY!" -m agents.core.uninstall --confirm !GUI! !PURGEDATA! !YESPURGE! !NOBACKUP!
set "RC=%errorlevel%"
echo.
if "!RC!"=="0" (
  echo   Done. Nerva's software footprint has been removed.
  echo   The repo checkout itself ^(source files^) is left in place -
  echo   delete this folder yourself if you're removing Nerva entirely.
) else (
  echo   [WARNING] uninstall reported problems - see the JSON report above.
)

:end
echo.
echo Press any key to close...
pause >nul
endlocal
