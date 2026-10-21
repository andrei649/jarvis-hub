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
REM          UNINSTALL.bat /CONFIRM /GUIONLY     (remove ONLY the desktop app;
REM                                               wins over /GUI in any order)
REM          UNINSTALL.bat /GUISUMMARY           (JSON probe of the desktop app)
REM          UNINSTALL.bat /CONFIRM /PURGEDATA   (also erase data; typed confirmation)
REM  Unknown switches are refused (exit 2) before anything is asked or removed.
REM  Scripted purge: batch argument parsing splits on '=', so the
REM  non-interactive confirmation comes from an environment variable:
REM    set "NERVA_YES_PURGE=<absolute path of the data root>"
REM    UNINSTALL.bat /CONFIRM /PURGEDATA
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Uninstall

set "DOCONFIRM=0"
set "PURGEDATA="
set "DRYRUN="
set "GUI="
set "GUIFLAG="
set "GUIONLY="
set "GUISUMMARY="
set "NOBACKUP="
set "YESPURGE="
set "VENVFLAG="
set "RC=0"
REM Refuse, never just ignore: a mistyped "/DRYRN /CONFIRM" must not become a real
REM uninstall (same rule as uninstall.sh). Nothing has been removed at this point.
for %%A in (%*) do (
  set "KNOWN=0"
  if /I "%%~A"=="/CONFIRM" (set "DOCONFIRM=1" & set "KNOWN=1")
  if /I "%%~A"=="/DRYRUN" (set "DRYRUN=--dry-run" & set "KNOWN=1")
  if /I "%%~A"=="/GUI" (set "GUIFLAG=1" & set "KNOWN=1")
  if /I "%%~A"=="/GUIONLY" (set "GUIONLY=1" & set "KNOWN=1")
  if /I "%%~A"=="/GUISUMMARY" (set "GUISUMMARY=1" & set "KNOWN=1")
  if /I "%%~A"=="/PURGEDATA" (set "PURGEDATA=--purge-data" & set "KNOWN=1")
  if /I "%%~A"=="/NOBACKUP" (set "NOBACKUP=--no-backup" & set "KNOWN=1")
  if "!KNOWN!"=="0" (
    echo [ERROR] unknown option %%~A - nothing was removed
    endlocal
    exit /b 2
  )
)
REM /GUIONLY wins over /GUI whatever their order, as in the module and uninstall.sh:
REM asking to keep the engine must never turn into a full uninstall.
if defined GUIONLY (set "GUI=--gui-only") else if defined GUIFLAG set "GUI=--gui"

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
REM     Each probe is a flat line tested with && : inside one parenthesised
REM     if/else block cmd expands the errorlevel variable once, at parse time, so a nested
REM     second check would always see the first probe's failure. Running the
REM     interpreter (not just "where") also skips the Microsoft Store python stub.
py -3 -c "import sys" >nul 2>&1 && (set "PY=py -3" & goto :havepy)
python -c "import sys" >nul 2>&1 && (set "PY=python" & goto :havepy)
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
  REM Only here: the module would otherwise refuse (it cannot delete the venv it runs
  REM from) and point back at this script. With the flag it removes everything else.
  set "VENVFLAG=--allow-locked-venv"
  echo [WARNING] no system Python found - running from .venv\Scripts\python.exe.
  echo           Windows locks a running interpreter, so .venv\ is left in place
  echo           ^(listed under not_removed^); delete it by hand after this window
  echo           closes, or install Python 3 ^(py -3^) and re-run to remove it too.
  goto :havepy
)
echo [ERROR] no Python found - cannot run the uninstall module.
set "RC=1"
goto :end
:havepy

if defined GUISUMMARY (
  !PY! -m agents.core.uninstall --gui-summary
  set "RC=!errorlevel!"
  goto :end
)
if defined DRYRUN (
  !PY! -m agents.core.uninstall --dry-run !GUI! !PURGEDATA! !VENVFLAG!
  set "RC=!errorlevel!"
  echo.
  echo   Dry run - nothing was removed. Re-run with /CONFIRM to proceed.
  goto :end
)
!PY! -m agents.core.uninstall --confirm !GUI! !PURGEDATA! !YESPURGE! !NOBACKUP! !VENVFLAG!
set "RC=!errorlevel!"
echo.
if "!RC!"=="0" (
  echo   Done. Nerva's software footprint has been removed.
  echo   The repo checkout itself ^(source files^) is left in place -
  echo   delete this folder yourself if you're removing Nerva entirely.
) else (
  echo   [WARNING] uninstall reported problems - see the messages above ^(the JSON report, or the module's refusal or error^).
)

:end
echo.
echo Press any key to close...
pause >nul
endlocal & exit /b %RC%
