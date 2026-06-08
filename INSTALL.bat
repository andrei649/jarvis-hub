@echo off
REM ============================================================
REM  JARVIS HUB - INSTALARE COMPLETA (first-time setup, Windows 11)
REM  Instaleaza TOT, intr-un singur fisier. Doar dubleaza-click.
REM    JARVIS:    Python 3.12, Git, venv + dependinte, teste
REM    WorldView: Node.js 20+, Docker Desktop, fisiere .env, npm install
REM  Pe un PC curat: cand instaleaza un program nou (Python/Git/Node/Docker)
REM  iti cere sa INCHIZI si sa rulezi INSTALL.bat DIN NOU (ca PATH-ul sa
REM  se actualizeze). A doua oara merge pana la capat.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Instalare completa

echo.
echo ============================================================
echo   JARVIS HUB + WorldView - INSTALARE COMPLETA DE LA ZERO
echo ============================================================
echo.

set "REPO_URL=https://github.com/andrei649/jarvis-hub.git"
set "NEED_RESTART=0"

REM ============================================================
REM  PARTEA 1 - Programe necesare (instalate prin winget daca lipsesc)
REM ============================================================

REM --- 1. Python 3.12 (necesar JARVIS) ------------------------
echo [1/7] Verific Python...
set "PY="
where py >nul 2>&1 && set "PY=py"
if "!PY!"=="" ( where python >nul 2>&1 && set "PY=python" )
if "!PY!"=="" (
  echo   [LIPSESTE] Python - incerc instalarea prin winget...
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo   [OK] Python instalat ^(necesita re-rulare INSTALL.bat^).
    set "NEED_RESTART=1"
  ) else (
    echo   winget indisponibil. Instaleaza Python manual ^(BIFEAZA "Add Python to PATH"^):
    echo   https://www.python.org/downloads/
    goto :end
  )
) else (
  !PY! --version
  echo   [OK] Python gasit.
)
echo.

REM --- 2. Git (necesar) ---------------------------------------
echo [2/7] Verific Git...
call :ensure_tool git Git.Git Git
set "RC=!errorlevel!"
if "!RC!"=="2" goto :end
if "!RC!"=="1" set "NEED_RESTART=1"
echo.

REM --- 3. Node.js 20+ (necesar WorldView) --------------------
echo [3/7] Verific Node.js ^(20+^)...
call :ensure_tool node OpenJS.NodeJS.LTS "Node.js LTS"
set "RC=!errorlevel!"
if "!RC!"=="2" goto :end
if "!RC!"=="1" set "NEED_RESTART=1"
echo.

REM --- 4. Docker Desktop (necesar infra WorldView) -----------
REM  Soft: daca instalarea Docker esueaza, NU blocheaza restul - JARVIS
REM  merge fara Docker, iar WorldView porneste cand Docker e disponibil.
echo [4/7] Verific Docker Desktop...
where docker >nul 2>&1
if !errorlevel!==0 (
  docker --version
  echo   [OK] Docker gasit.
) else (
  echo   [LIPSESTE] Docker Desktop.
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    echo   Incerc instalarea prin winget ^(descarcare mare; poate cere REPORNIRE + WSL2^)...
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if !errorlevel!==0 (
      echo   [OK] Docker instalat. PORNESTE-l manual prima data ^(accepta licenta + lasa WSL2 sa termine^).
      set "NEED_RESTART=1"
    ) else (
      echo   [ATENTIE] Instalarea Docker a esuat. Instaleaza manual:
      echo            https://www.docker.com/products/docker-desktop/
      echo            ^(WorldView are nevoie de Docker; JARVIS merge si fara.^)
    )
  ) else (
    echo   winget indisponibil. Instaleaza Docker manual:
    echo   https://www.docker.com/products/docker-desktop/
  )
)
echo.

if "!NEED_RESTART!"=="1" (
  echo ============================================================
  echo   [IMPORTANT] Am instalat programe noi.
  echo   INCHIDE aceasta fereastra si ruleaza INSTALL.bat DIN NOU,
  echo   ca Windows sa le recunoasca in PATH.
  echo   ^(Daca s-a instalat Docker Desktop, porneste-l manual prima data.^)
  echo ============================================================
  goto :end
)

REM ============================================================
REM  PARTEA 2 - Cod + dependinte (toate programele sunt prezente)
REM ============================================================

REM --- 5. Aduc codul -----------------------------------------
echo [5/7] Aduc codul proiectului...
if exist "serve.py" (
  echo   Sunt deja in folderul proiectului. Aduc ultimele modificari...
  git pull --rebase origin main
) else (
  if exist "jarvis-hub\serve.py" (
    echo   Proiectul exista in .\jarvis-hub - il actualizez...
    cd jarvis-hub
    git pull --rebase origin main
  ) else (
    echo   Clonez de pe GitHub...
    git clone %REPO_URL%
    if !errorlevel! neq 0 ( echo   [EROARE] Clonarea a esuat. Verifica internetul/accesul la repo. & goto :end )
    cd jarvis-hub
  )
)
echo.

REM --- 6. JARVIS: venv + dependinte --------------------------
echo [6/7] JARVIS: mediu Python + dependinte...
set "PY="
where py >nul 2>&1 && set "PY=py"
if "!PY!"=="" set "PY=python"
if not exist ".venv\Scripts\python.exe" ( !PY! -m venv .venv )
set "VPY=.venv\Scripts\python.exe"
"!VPY!" -m pip install --quiet --upgrade pip
"!VPY!" -m pip install --quiet -r requirements-beta.txt
echo   [OK] Dependinte JARVIS instalate.
echo.

REM --- 7. WorldView: .env + npm install ----------------------
echo [7/7] WorldView: configurare + dependinte Node...
if exist "worldview\package.json" (
  REM Scaffold .env-urile din exemple - NU suprascrie ce ai deja completat.
  if not exist "worldview\.env" copy /Y "worldview\.env.example" "worldview\.env" >nul
  if not exist "worldview\backend-api\.env" copy /Y "worldview\backend-api\.env.example" "worldview\backend-api\.env" >nul
  if not exist "worldview\frontend\.env.local" copy /Y "worldview\frontend\.env.local.example" "worldview\frontend\.env.local" >nul
  echo   [OK] Fisiere .env create ^(cheile pentru feed-uri live + Mapbox sunt optionale^).
  echo   Instalez dependintele Node ^(dureaza cateva minute prima data^)...
  pushd worldview
  call npm install
  set "NPMRC=!errorlevel!"
  popd
  if "!NPMRC!"=="0" ( echo   [OK] WorldView gata. ) else ( echo   [ATENTIE] npm install a raportat erori - vezi mesajele de mai sus. )
) else (
  echo   [SKIP] Folderul worldview lipseste in acest checkout.
)
echo.

REM --- Verificare optionala cu testele JARVIS ----------------
echo Verific cu testele JARVIS ^(optional^)...
echo ------------------------------------------------------------
"!VPY!" -m pytest -q
set "TESTRC=!errorlevel!"
echo ------------------------------------------------------------
echo.

echo ============================================================
if "!TESTRC!"=="0" (
  echo   [GATA] Instalare completa reusita!
) else (
  echo   [GATA] Instalat ^(unele teste au esuat - poti incerca oricum^).
)
echo   Porneste tot:            START.bat          ^(JARVIS :8080 + WorldView :3000^)
echo   Doar JARVIS:             set JARVIS_WORLDVIEW=0   apoi  START.bat
echo   Date demo in WorldView:  in folderul worldview,  npm run db:seed
echo   Actualizeaza oricand:    UPDATE.bat
echo ============================================================
goto :end

REM ============================================================
REM  Subrutina: asigura un program de linie de comanda
REM    %1 = comanda de probat (ex. git)   %2 = winget id   %3 = nume prietenos
REM  Cod retur: 0 = prezent · 1 = instalat acum (necesita re-rulare) · 2 = winget lipseste
REM ============================================================
:ensure_tool
where %~1 >nul 2>&1
if !errorlevel!==0 (
  %~1 --version
  echo   [OK] %~3 gasit.
  exit /b 0
)
echo   [LIPSESTE] %~3 - incerc instalarea prin winget...
winget --version >nul 2>&1
if !errorlevel! neq 0 (
  echo   winget indisponibil. Instaleaza %~3 manual, apoi ruleaza INSTALL.bat din nou.
  exit /b 2
)
winget install -e --id %~2 --accept-package-agreements --accept-source-agreements
echo   [OK] %~3 instalat ^(necesita re-rulare INSTALL.bat^).
exit /b 1

:end
echo.
echo Apasa o tasta pentru a inchide...
pause >nul
endlocal
