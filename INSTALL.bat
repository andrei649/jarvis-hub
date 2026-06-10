@echo off
REM ============================================================
REM  JARVIS HUB - FULL INSTALL (first-time setup, Windows 11)
REM  Installs EVERYTHING from one file. Just double-click.
REM    JARVIS:    Python 3.12, Git, venv + dependencies, tests
REM    WorldView: Node.js 20+, Docker Desktop, .env files, npm install
REM  On a clean PC: whenever a new program is installed (Python/Git/
REM  Node/Docker) it asks you to CLOSE and run INSTALL.bat AGAIN (so
REM  PATH gets refreshed). The second run goes all the way through.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Full install

echo.
echo ============================================================
echo   JARVIS HUB + WorldView - FULL INSTALL FROM SCRATCH
echo ============================================================
echo.

set "REPO_URL=https://github.com/andrei649/jarvis-hub.git"
set "NEED_RESTART=0"

REM ============================================================
REM  PART 1 - Required programs (installed via winget if missing)
REM ============================================================

REM --- 1. Python 3.12 (required by JARVIS) --------------------
echo [1/7] Checking Python...
set "PY="
where py >nul 2>&1 && set "PY=py"
if "!PY!"=="" ( where python >nul 2>&1 && set "PY=python" )
if "!PY!"=="" (
  echo   [MISSING] Python - trying to install via winget...
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo   [OK] Python installed ^(requires re-running INSTALL.bat^).
    set "NEED_RESTART=1"
  ) else (
    echo   winget unavailable. Install Python manually ^(CHECK "Add Python to PATH"^):
    echo   https://www.python.org/downloads/
    goto :end
  )
) else (
  !PY! --version
  echo   [OK] Python found.
)
echo.

REM --- 2. Git (required) --------------------------------------
echo [2/7] Checking Git...
call :ensure_tool git Git.Git Git
set "RC=!errorlevel!"
if "!RC!"=="2" goto :end
if "!RC!"=="1" set "NEED_RESTART=1"
echo.

REM --- 3. Node.js 20+ (required by WorldView) -----------------
echo [3/7] Checking Node.js ^(20+^)...
call :ensure_tool node OpenJS.NodeJS.LTS "Node.js LTS"
set "RC=!errorlevel!"
if "!RC!"=="2" goto :end
if "!RC!"=="1" set "NEED_RESTART=1"
echo.

REM --- 4. Docker Desktop (required by WorldView infra) --------
REM  Soft requirement: if the Docker install fails it does NOT block
REM  the rest - JARVIS runs without Docker, and WorldView starts
REM  whenever Docker becomes available.
echo [4/7] Checking Docker Desktop...
where docker >nul 2>&1
if !errorlevel!==0 (
  docker --version
  echo   [OK] Docker found.
) else (
  echo   [MISSING] Docker Desktop.
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    echo   Trying to install via winget ^(large download; may require a RESTART + WSL2^)...
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    if !errorlevel!==0 (
      echo   [OK] Docker installed. START it manually the first time ^(accept the license + let WSL2 finish^).
      set "NEED_RESTART=1"
    ) else (
      echo   [WARNING] Docker install failed. Install manually:
      echo            https://www.docker.com/products/docker-desktop/
      echo            ^(WorldView needs Docker; JARVIS runs without it.^)
    )
  ) else (
    echo   winget unavailable. Install Docker manually:
    echo   https://www.docker.com/products/docker-desktop/
  )
)
echo.

if "!NEED_RESTART!"=="1" (
  echo ============================================================
  echo   [IMPORTANT] New programs were installed.
  echo   CLOSE this window and run INSTALL.bat AGAIN,
  echo   so Windows picks them up in PATH.
  echo   ^(If Docker Desktop was installed, start it manually first.^)
  echo ============================================================
  goto :end
)

REM ============================================================
REM  PART 2 - Code + dependencies (all programs are present)
REM ============================================================

REM --- 5. Fetch the code --------------------------------------
echo [5/7] Fetching the project code...
if exist "serve.py" (
  echo   Already inside the project folder. Pulling latest changes...
  git pull --rebase origin main
) else (
  if exist "jarvis-hub\serve.py" (
    echo   Project exists in .\jarvis-hub - updating it...
    cd jarvis-hub
    git pull --rebase origin main
  ) else (
    echo   Cloning from GitHub...
    git clone %REPO_URL%
    if !errorlevel! neq 0 ( echo   [ERROR] Clone failed. Check your internet/repo access. & goto :end )
    cd jarvis-hub
  )
)
echo.

REM --- 6. JARVIS: venv + dependencies -------------------------
echo [6/7] JARVIS: Python environment + dependencies...
set "PY="
where py >nul 2>&1 && set "PY=py"
if "!PY!"=="" set "PY=python"
if not exist ".venv\Scripts\python.exe" ( !PY! -m venv .venv )
set "VPY=.venv\Scripts\python.exe"
"!VPY!" -m pip install --quiet --upgrade pip
"!VPY!" -m pip install --quiet -r requirements-beta.txt
echo   [OK] JARVIS dependencies installed.
echo.

REM --- 7. WorldView: .env + npm install ------------------------
echo [7/7] WorldView: configuration + Node dependencies...
if exist "worldview\package.json" (
  REM Scaffold the .env files from the examples - do NOT overwrite anything you filled in.
  if not exist "worldview\.env" copy /Y "worldview\.env.example" "worldview\.env" >nul
  if not exist "worldview\backend-api\.env" copy /Y "worldview\backend-api\.env.example" "worldview\backend-api\.env" >nul
  if not exist "worldview\frontend\.env.local" copy /Y "worldview\frontend\.env.local.example" "worldview\frontend\.env.local" >nul
  if not exist "worldview\ingestion-workers\.env" copy /Y "worldview\ingestion-workers\.env.example" "worldview\ingestion-workers\.env" >nul
  echo   [OK] .env files created ^(keys for live feeds + Mapbox are optional^).
  echo   Installing Node dependencies ^(takes a few minutes the first time^)...
  pushd worldview
  call npm install
  set "NPMRC=!errorlevel!"
  popd
  if "!NPMRC!"=="0" ( echo   [OK] WorldView ready. ) else ( echo   [WARNING] npm install reported errors - see the messages above. )
  REM Python environment for the OSINT ingestion workers (REAL data: aircraft/satellites/jamming).
  if exist "worldview\ingestion-workers\requirements.txt" (
    if not exist "worldview\ingestion-workers\.venv\Scripts\python.exe" (
      echo   Preparing the OSINT worker environment ^(for real data; optional, takes a moment^)...
      %PY% -m venv "worldview\ingestion-workers\.venv"
      "worldview\ingestion-workers\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
      "worldview\ingestion-workers\.venv\Scripts\python.exe" -m pip install --quiet -r "worldview\ingestion-workers\requirements.txt"
      echo   [OK] OSINT workers ready ^(enable real data with  set JARVIS_WORLDVIEW_FEED=real  then START.bat^).
    )
  )
) else (
  echo   [SKIP] The worldview folder is missing in this checkout.
)
echo.

REM --- Optional verification with the JARVIS tests -------------
echo Verifying with the JARVIS tests ^(optional^)...
echo ------------------------------------------------------------
"!VPY!" -m pytest -q
set "TESTRC=!errorlevel!"
echo ------------------------------------------------------------
echo.

echo ============================================================
if "!TESTRC!"=="0" (
  echo   [DONE] Full install succeeded!
) else (
  echo   [DONE] Installed ^(some tests failed - you can still try it^).
)
echo   Start everything:        START.bat          ^(JARVIS :8080 + WorldView :3000^)
echo   JARVIS only:             set JARVIS_WORLDVIEW=0   then  START.bat
echo   Demo data in WorldView:  inside the worldview folder,  npm run db:seed
echo   Update any time:         UPDATE.bat
echo ============================================================
goto :end

REM ============================================================
REM  Subroutine: ensure a command-line tool is present
REM    %1 = command to probe (e.g. git)   %2 = winget id   %3 = friendly name
REM  Return code: 0 = present · 1 = just installed (re-run needed) · 2 = winget missing
REM ============================================================
:ensure_tool
where %~1 >nul 2>&1
if !errorlevel!==0 (
  %~1 --version
  echo   [OK] %~3 found.
  exit /b 0
)
echo   [MISSING] %~3 - trying to install via winget...
winget --version >nul 2>&1
if !errorlevel! neq 0 (
  echo   winget unavailable. Install %~3 manually, then run INSTALL.bat again.
  exit /b 2
)
winget install -e --id %~2 --accept-package-agreements --accept-source-agreements
echo   [OK] %~3 installed ^(requires re-running INSTALL.bat^).
exit /b 1

:end
echo.
echo Press any key to close...
pause >nul
endlocal
