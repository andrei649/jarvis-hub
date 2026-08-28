@echo off
REM ============================================================
REM  JARVIS HUB - UNINSTALL (Windows 11, double-click)
REM  Removes the installer-created software footprint: .venv\,
REM  WorldView's node_modules\ and generated .env files. Your
REM  DATA (memory_logs\ or %JARVIS_HOME%) is NOT touched unless
REM  you also pass /PURGEDATA.
REM
REM  Usage:  UNINSTALL.bat            (asks for confirmation)
REM          UNINSTALL.bat /CONFIRM   (no prompt, for scripting)
REM          UNINSTALL.bat /CONFIRM /PURGEDATA   (also erase data)
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Uninstall

set "DOCONFIRM=0"
set "PURGEDATA="
for %%A in (%*) do (
  if /I "%%~A"=="/CONFIRM" set "DOCONFIRM=1"
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

"!PY!" -m agents.core.uninstall --confirm !PURGEDATA! !NOBACKUP!
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
