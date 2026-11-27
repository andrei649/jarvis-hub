@echo off
REM ============================================================
REM  NERVA - START  (Windows 11, double-click)
REM  Starts the server (loopback, :8080) and opens the Command
REM  Center (http://127.0.0.1:8080/v2) in your browser once
REM  /readyz answers.
REM    START.bat doctor   runs the install check-up instead
REM                       (scripts\doctor.py; changes nothing)
REM  Run UPDATE.bat first if you want the latest version.
REM  Phone / second device: docs\PHONE_ACCESS.md (token-gated).
REM ============================================================
setlocal enableextensions
cd /d "%~dp0"
title Nerva - Server

REM --- Pick the venv python if it exists, else system python ---
if exist ".venv\Scripts\python.exe" (
  set "VPY=.venv\Scripts\python.exe"
) else (
  where py >nul 2>&1
  if %errorlevel%==0 (set "VPY=py") else (set "VPY=python")
  echo [INFO] No .venv found - run INSTALL.bat first. Using the global Python.
)

REM --- START.bat doctor: the install check-up, then exit ------
if /I "%~1"=="doctor" (
  "%VPY%" scripts\doctor.py
  echo.
  pause
  exit /b
)

echo.
echo ============================================================
echo   NERVA - STARTING
echo ============================================================
echo.

REM The V2 HUD (cockpit) is the primary one from now on; override with  set JARVIS_HUD=v1  for the legacy HUD.
REM RB-2: a NERVA_HUD you set is left alone (a JARVIS_HUD default beside it would be a conflict).
if not defined JARVIS_HUD if not defined NERVA_HUD set "JARVIS_HUD=v2"
echo Starting the server on http://127.0.0.1:8080  ^(loopback only^)
echo Command Center: http://127.0.0.1:8080/v2   ^(legacy HUD at /v1^)
echo Vault and Memory Copilot status follows after serve.py loads the local .env.
echo Admin:        http://127.0.0.1:8080/admin
echo.
echo (Keep this window open. Close it to stop the server.)
echo.

REM Open the Command Center once /readyz answers (poll loopback; give up after ~2 min).
if not defined NERVA_NO_BROWSER start "" /b powershell -NoProfile -Command "Write-Host 'Waiting for the server to start...'; $n = 0; while ($n -lt 60) { $n++; try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/readyz' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8080/v2'; break } } catch { Start-Sleep 2 } }"

"%VPY%" serve.py

echo.
echo The server has stopped.
pause >nul
endlocal
exit /b
