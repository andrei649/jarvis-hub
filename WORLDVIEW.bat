@echo off
REM ============================================================
REM  WORLDVIEW - START  (Windows 11, double-click)
REM  Brings up the WorldView 4D OSINT command center:
REM    - infra (Redpanda + TimescaleDB + Redis) via Docker
REM    - installs Node deps (first run only)
REM    - seeds a demo scenario (historical + live)
REM    - starts the API (4000) and the dashboard (3000)
REM    - opens the globe in your browser
REM  NOTE: this is SEPARATE from START.bat (the JARVIS HUB on 8080).
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0worldview"
title WorldView - 4D OSINT

echo.
echo ============================================================
echo   WORLDVIEW - PORNIRE
echo ============================================================
echo.

REM --- 1. Docker must be installed AND running -----------------
docker info >nul 2>&1
if errorlevel 1 (
  echo [EROARE] Docker nu ruleaza ^(sau nu e instalat^).
  echo Porneste Docker Desktop si asteapta sa fie "running", apoi reia.
  echo Descarca: https://www.docker.com/products/docker-desktop/
  goto :end
)

REM --- 2. Node / npm -------------------------------------------
where npm >nul 2>&1
if errorlevel 1 (
  echo [EROARE] Node.js / npm nu e in PATH ^(necesar Node ^>=20^).
  echo Descarca: https://nodejs.org/
  goto :end
)

REM --- 3. Infra (Redpanda + TimescaleDB + Redis) --------------
echo [1/5] Pornesc infrastructura ^(Docker: Redpanda + TimescaleDB + Redis^)...
docker compose up -d
if errorlevel 1 (
  echo [EROARE] "docker compose up -d" a esuat ^(vezi mesajul de mai sus^).
  goto :end
)

echo     Astept ca TimescaleDB sa fie gata...
set /a _tries=0
:waitdb
docker compose exec -T timescaledb pg_isready -U worldview -d worldview >nul 2>&1
if not errorlevel 1 goto :dbready
set /a _tries+=1
if !_tries! geq 30 (
  echo [ATENTIE] TimescaleDB nu a raspuns in ~60s; continui oricum.
  goto :dbready
)
timeout /t 2 >nul
goto :waitdb
:dbready
echo     TimescaleDB e gata.
echo.

REM --- 4. Node deps (prima rulare) ----------------------------
if not exist "node_modules" (
  echo [2/5] Instalez dependentele Node ^(frontend + backend-api^)...
  call npm install
  if errorlevel 1 (
    echo [EROARE] npm install a esuat.
    goto :end
  )
) else (
  echo [2/5] Dependentele Node exista deja ^(skip^).
)
echo.

REM --- 5. Seed demo data (historical + live) ------------------
echo [3/5] Incarc scenariul demo ^(Stramtoarea Hormuz, ultimele ~10 min^)...
docker compose exec -T timescaledb psql -U worldview -d worldview -v ON_ERROR_STOP=1 < db\seed\demo.sql >nul 2>&1
if errorlevel 1 (
  echo     [ATENTIE] Seed istoric a esuat ^(poate schema nu e gata^); continui.
) else (
  echo     Seed istoric OK ^(scrub-uieste timeline-ul ~10 min in urma^).
)
set "REDIS_URL=redis://localhost:6379"
node scripts\seed-live.mjs >nul 2>&1
if errorlevel 1 (
  echo     [ATENTIE] Seed LIVE ^(Redis^) a esuat; continui.
) else (
  echo     Seed LIVE OK ^(modul LIVE arata date imediat^).
)
echo.

REM --- 6. Start API + dashboard in ferestre separate ----------
echo [4/5] Pornesc API-ul ^(4000^) si dashboard-ul ^(3000^)...
start "WorldView API (4000)" cmd /k npm run dev:api
start "WorldView UI (3000)" cmd /k npm run dev:frontend

echo [5/5] Astept dashboard-ul si deschid browserul...
echo.
echo   Dashboard: http://localhost:3000
echo   API:       http://localhost:4000/health
echo   Broker UI: http://localhost:8085  ^(Redpanda console^)
echo.
echo   NOTA: pentru harta de baza ai nevoie de un MAPBOX_ACCESS_TOKEN
echo         in worldview\frontend\.env.local. Fara el, comuta pe globul 3D
echo         ^(toggle-ul din UI deseneaza un glob offline, fara Mapbox^).
echo.
echo   Cele doua ferestre noi ^(API/UI^) tin serverele pornite.
echo   Inchide-le ca sa opresti WorldView. "docker compose down" opreste infra.
echo.

start "" /b powershell -NoProfile -Command "Write-Host 'Astept pornirea dashboard-ului...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://localhost:3000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://localhost:3000/'; break } } catch { Start-Sleep 3 } }"

echo Gata. Aceasta fereastra se poate inchide.
:end
echo.
echo Apasa o tasta pentru a inchide...
pause >nul
endlocal
