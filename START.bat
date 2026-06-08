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
echo   JARVIS HUB - PORNIRE
echo ============================================================
echo.

REM --- Pick the venv python if it exists, else system python ---
if exist ".venv\Scripts\python.exe" (
  set "VPY=.venv\Scripts\python.exe"
) else (
  where py >nul 2>&1
  if %errorlevel%==0 (set "VPY=py") else (set "VPY=python")
  echo [INFO] Nu exista .venv - folosesc Python global.
  echo        Recomandat: ruleaza intai UPDATE.bat.
)

REM --- WorldView (4D OSINT) - pornire automata (optional, opt-out cu JARVIS_WORLDVIEW=0) ---
if /I "%JARVIS_WORLDVIEW%"=="0" (
  echo [INFO] WorldView dezactivat ^(JARVIS_WORLDVIEW=0^) - pornesc doar JARVIS.
) else (
  call :start_worldview
)

echo.
echo Pornesc serverul pe http://127.0.0.1:8080
echo HUD:   http://127.0.0.1:8080/
echo Admin: http://127.0.0.1:8080/admin
echo.
echo (Lasa aceasta fereastra deschisa. Inchide-o ca sa opresti serverul.)
echo.

REM Open the browser once the server is listening (poll port 8080).
start "" /b powershell -NoProfile -Command "Write-Host 'Astept pornirea serverului...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8080/'; break } } catch { Start-Sleep 3 } }"

"%VPY%" serve.py

echo.
echo Serverul s-a oprit.
echo (WorldView, daca a pornit, ruleaza in ferestrele sale separate - inchide-le manual.)
pause >nul
endlocal
exit /b

REM ============================================================
REM  Subrutina: porneste WorldView (infra Docker + API + Frontend)
REM  Sare gratios daca lipseste Docker / Node / node_modules,
REM  ca JARVIS sa porneasca oricum.
REM ============================================================
:start_worldview
echo.
echo ------------------------------------------------------------
echo   WorldView (4D OSINT) - pornire automata
echo ------------------------------------------------------------
where docker >nul 2>&1 || (echo [SKIP] Docker negasit - sar peste WorldView ^(porneste Docker Desktop si reincearca^). & goto :eof)
where npm >nul 2>&1 || (echo [SKIP] Node/npm negasit ^(necesar Node 20+^) - sar peste WorldView. & goto :eof)
if not exist "worldview\node_modules" (
  echo [SKIP] worldview\node_modules lipseste. Ruleaza intai, o singura data:
  echo          cd worldview ^&^& npm install
  goto :eof
)

echo [1/3] Pornesc infra ^(TimescaleDB + Redis + Redpanda^) via docker compose...
pushd "%~dp0worldview"
docker compose up -d
if errorlevel 1 (
  echo [SKIP] docker compose a esuat ^(e pornit Docker Desktop?^) - sar peste WorldView.
  popd
  goto :eof
)
popd

echo [2/3] Pornesc WorldView API ^(:4000^) si Frontend ^(:3000^) in ferestre separate...
start "WorldView API" /d "%~dp0worldview" cmd /k "npm run dev:api"
start "WorldView Frontend" /d "%~dp0worldview" cmd /k "npm run dev:frontend"

echo [3/3] Voi deschide http://localhost:3000 cand e gata.
echo       ^(Prima pornire dureaza ceva - Next.js compileaza. Lasa ferestrele WorldView deschise.^)
start "" /b powershell -NoProfile -Command "Write-Host 'Astept WorldView (:3000)...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://localhost:3000/'; break } } catch { Start-Sleep 3 } }"
goto :eof
