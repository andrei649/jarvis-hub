@echo off
REM ============================================================
REM  NERVA - START  (Windows 11, double-click)
REM  Starts the server (loopback, :8080) and opens the Command
REM  Center (http://127.0.0.1:8080/v2) in your browser once
REM  /readyz answers.
REM    START.bat doctor   runs the install check-up instead
REM                       (scripts\doctor.py; changes nothing)
REM  OPT-IN companions - they no longer auto-start.
REM  Run UPDATE.bat first if you want the latest version.
REM  Phone / second device: docs\PHONE_ACCESS.md (token-gated).
REM
REM  Signal Layer is OPT-IN: to also start it, run with
REM    set JARVIS_SIGNAL_LAYER=1
REM  Signal Layer live mode is OPT-IN:
REM    set JARVIS_SIGNAL_LAYER_MODE=live
REM    set WORLDMONITOR_BASE_URL=http://localhost:3100
REM    set WORLDMONITOR_MCP_URL=http://localhost:3100/api/mcp
REM  (or set any of these permanently in your environment).
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

REM --- Jarvis Signal Layer - opt-IN with JARVIS_SIGNAL_LAYER=1 ---
if /I "%JARVIS_SIGNAL_LAYER%"=="1" (
  call :start_signal_layer
)

echo.
REM The V2 HUD (cockpit) is the primary one from now on; override with  set JARVIS_HUD=v1  for the legacy HUD.
if not defined JARVIS_HUD set "JARVIS_HUD=v2"
echo Starting the server on http://127.0.0.1:8080  ^(loopback only^)
echo Command Center: http://127.0.0.1:8080/v2   ^(legacy HUD at /v1^)
echo Admin:        http://127.0.0.1:8080/admin
echo Signal Layer: http://127.0.0.1:8787/healthz ^(if started^)
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

REM ============================================================
REM  Skips gracefully if Docker / Node / node_modules are missing,
REM  so JARVIS starts anyway.
REM ============================================================
:start_signal_layer
echo.
echo ------------------------------------------------------------
echo   Jarvis Signal Layer - auto-start
echo ------------------------------------------------------------
where node >nul 2>&1 || (echo [SKIP] Node not found ^(Node 20+ required^) - skipping Signal Layer. & goto :eof)
if not exist "services\signal-layer\src\index.mjs" (
  echo [SKIP] services\signal-layer is missing - skipping Signal Layer.
  goto :eof
)
if not defined JARVIS_SIGNAL_LAYER_MODE (
)
if not defined JARVIS_SIGNAL_LAYER_MODE set "JARVIS_SIGNAL_LAYER_MODE=replay"
if not defined SIGNAL_LAYER_HOST set "SIGNAL_LAYER_HOST=127.0.0.1"
if not defined SIGNAL_LAYER_PORT set "SIGNAL_LAYER_PORT=8787"
echo [INFO] Mode: %JARVIS_SIGNAL_LAYER_MODE%  Port: %SIGNAL_LAYER_PORT%
echo [INFO] Starting Signal Layer in a separate window...
start "Jarvis Signal Layer" /d "%~dp0services\signal-layer" cmd /k "node src\index.mjs"
goto :eof
