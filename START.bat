@echo off
REM ============================================================
REM  JARVIS HUB - START  (Windows 11, double-click)
REM  Starts the server and opens the HUD in your browser.
REM  Also auto-starts WorldView (4D OSINT) if it's set up.
REM  Run UPDATE.bat first if you want the latest version.
REM
REM  WorldView is OPT-OUT: to start JARVIS only, run with
REM    set JARVIS_WORLDVIEW=0
REM  (or set it permanently in your environment).
REM ============================================================
setlocal enableextensions
cd /d "%~dp0"
title JARVIS HUB - Server

echo.
echo ============================================================
echo   JARVIS HUB - STARTING
echo ============================================================
echo.

REM --- Pick the venv python if it exists, else system python ---
if exist ".venv\Scripts\python.exe" (
  set "VPY=.venv\Scripts\python.exe"
) else (
  where py >nul 2>&1
  if %errorlevel%==0 (set "VPY=py") else (set "VPY=python")
  echo [INFO] No .venv found - using the global Python.
  echo        Recommended: run UPDATE.bat first.
)

REM --- WorldView (4D OSINT) - auto-start (optional, opt-out with JARVIS_WORLDVIEW=0) ---
if /I "%JARVIS_WORLDVIEW%"=="0" (
  echo [INFO] WorldView disabled ^(JARVIS_WORLDVIEW=0^) - starting JARVIS only.
) else (
  call :start_worldview
)

echo.
REM The V2 HUD (cockpit) is the primary one from now on; override with  set JARVIS_HUD=v1  for the legacy HUD.
if not defined JARVIS_HUD set "JARVIS_HUD=v2"
echo Starting the server on http://127.0.0.1:8080
echo HUD:   http://127.0.0.1:8080/   ^(V2 cockpit; legacy HUD at /v1^)
echo Admin: http://127.0.0.1:8080/admin
echo.
echo (Keep this window open. Close it to stop the server.)
echo.

REM Open the browser once the server is listening (poll port 8080).
start "" /b powershell -NoProfile -Command "Write-Host 'Waiting for the server to start...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8080/'; break } } catch { Start-Sleep 3 } }"

"%VPY%" serve.py

echo.
echo The server has stopped.
echo (WorldView, if it started, runs in its own windows - close them manually.)
pause >nul
endlocal
exit /b

REM ============================================================
REM  Subroutine: start WorldView (Docker infra + API + Frontend)
REM  Skips gracefully if Docker / Node / node_modules are missing,
REM  so JARVIS starts anyway.
REM ============================================================
:start_worldview
echo.
echo ------------------------------------------------------------
echo   WorldView (4D OSINT) - auto-start
echo ------------------------------------------------------------
where docker >nul 2>&1 || (echo [SKIP] Docker not found - skipping WorldView ^(start Docker Desktop and retry^). & goto :eof)
where npm >nul 2>&1 || (echo [SKIP] Node/npm not found ^(Node 20+ required^) - skipping WorldView. & goto :eof)
if not exist "worldview\node_modules" (
  echo [SKIP] worldview\node_modules is missing. Run this once first:
  echo          cd worldview ^&^& npm install
  goto :eof
)

echo [1/3] Starting infra ^(TimescaleDB + Redis + Redpanda^) via docker compose...
pushd "%~dp0worldview"
docker compose up -d
if errorlevel 1 (
  echo [SKIP] docker compose failed ^(is Docker Desktop running?^) - skipping WorldView.
  popd
  goto :eof
)
popd

REM Feed mode: demo (default, synthetic) | real (REAL OSINT data, no keys for 3/4 layers) | off.
set "WV_FEED=demo"
if defined JARVIS_WORLDVIEW_FEED set "WV_FEED=%JARVIS_WORLDVIEW_FEED%"
if /I "%JARVIS_WORLDVIEW_DEMO%"=="0" if not defined JARVIS_WORLDVIEW_FEED set "WV_FEED=off"

echo [2/3] Starting WorldView API ^(:4000^) and Frontend ^(:3000^) in separate windows...
if /I "%WV_FEED%"=="real" (
  start "WorldView API" /d "%~dp0worldview" cmd /k "set ENABLE_LIVE_WRITER=1&&set ENABLE_HISTORY_WRITER=1&&npm run dev:api"
) else (
  start "WorldView API" /d "%~dp0worldview" cmd /k "npm run dev:api"
)
start "WorldView Frontend" /d "%~dp0worldview" cmd /k "npm run dev:frontend"

if /I "%WV_FEED%"=="real" (
  if exist "worldview\ingestion-workers\.venv\Scripts\python.exe" (
    echo       REAL mode: starting the free OSINT workers ^(aircraft/satellites/jamming/recon^)...
    start "WV aircraft adsb.fi" /d "%~dp0worldview\ingestion-workers" cmd /k "set ADSB_SOURCE=adsbfi&&.venv\Scripts\python -m worldview_ingest adsb"
    start "WV satellites Celestrak" /d "%~dp0worldview\ingestion-workers" cmd /k ".venv\Scripts\python -m worldview_ingest tle"
    start "WV gps-jamming" /d "%~dp0worldview\ingestion-workers" cmd /k ".venv\Scripts\python -m worldview_ingest ew"
    start "WV recon passes" /d "%~dp0worldview\ingestion-workers" cmd /k ".venv\Scripts\python -m worldview_ingest recon"
    echo       ^(Ships: put a free AISStream key in worldview\ingestion-workers\.env, then  python -m worldview_ingest ais^)
  ) else (
    echo [SKIP] REAL mode requested, but worldview\ingestion-workers\.venv is missing - run INSTALL.bat first.
  )
) else (
  if /I "%WV_FEED%"=="off" (
    echo [INFO] Feed disabled ^(WV_FEED=off^) - the map stays empty until you start a feed.
  ) else (
    echo       Starting the synthetic demo feed ^(keeps the map alive, no API keys^). Real data:  set JARVIS_WORLDVIEW_FEED=real
    start "WorldView Demo Feed" /d "%~dp0worldview" cmd /k "npm run demo:feed"
  )
)

echo [3/3] Will open http://localhost:3000 when it's ready.
echo       ^(The first start takes a while - Next.js is compiling. Keep the WorldView windows open.^)
start "" /b powershell -NoProfile -Command "Write-Host 'Waiting for WorldView (:3000)...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://localhost:3000/'; break } } catch { Start-Sleep 3 } }"
goto :eof
