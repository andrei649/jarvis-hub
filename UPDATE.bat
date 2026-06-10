@echo off
REM ============================================================
REM  JARVIS HUB - UPDATE & TEST  (Windows 11, double-click)
REM  Pulls latest from GitHub, installs deps (JARVIS + WorldView), runs the tests.
REM  No terminal knowledge needed - just double-click this file.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Update ^& Test

echo.
echo ============================================================
echo   JARVIS HUB - UPDATE ^& TEST
echo ============================================================
echo.

REM --- 1. Find Python -----------------------------------------
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (set "PY=python")
%PY% --version >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Python is not installed or not in PATH.
  echo Download it from https://www.python.org/downloads/ and check
  echo "Add Python to PATH" during installation.
  goto :end
)

REM --- 2. Pull latest from GitHub -----------------------------
echo [1/5] Pulling the latest changes from GitHub...
git pull --rebase origin main
if %errorlevel% neq 0 (
  echo.
  echo [WARNING] git pull failed. You may have unsaved local changes.
  echo Run in a terminal:  git status
  goto :end
)
echo.

REM --- 3. Virtual env + dependencies --------------------------
echo [2/5] Preparing the Python environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
  echo     Creating the virtual environment for the first time...
  %PY% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"

echo [3/5] Installing JARVIS dependencies...
"%VPY%" -m pip install --quiet --upgrade pip
"%VPY%" -m pip install --quiet -r requirements-beta.txt
echo.

REM --- 4. WorldView: refresh Node dependencies (if present) ----
echo [4/5] WorldView: updating Node dependencies...
if exist "worldview\package.json" (
  where npm >nul 2>&1
  if !errorlevel!==0 (
    pushd worldview
    call npm install
    popd
    echo   [OK] WorldView updated.
  ) else (
    echo   [SKIP] npm not found - skipping WorldView ^(JARVIS is updated^).
  )
) else (
  echo   [SKIP] worldview is missing in this checkout.
)
echo.

REM --- 5. Run the tests ---------------------------------------
echo [5/5] Running the tests...
echo ------------------------------------------------------------
"%VPY%" -m pytest -q
set "TESTRC=%errorlevel%"
echo ------------------------------------------------------------
echo.
if "%TESTRC%"=="0" (
  echo   [OK] Everything passed. Start the app with START.bat
) else (
  echo   [WARNING] Some tests failed ^(see above^).
)

:end
echo.
echo Press any key to close...
pause >nul
endlocal
