@echo off
REM ============================================================
REM  NERVA - ONE-STEP INSTALL (Windows 11, double-click)
REM  Ends with Nerva running and the Command Center open in your
REM  browser (http://127.0.0.1:8080/v2).
REM
REM  What it does:
REM    1. Python 3.12+ (installed via winget if missing - then re-run)
REM    2. The code (git clone if you double-clicked this outside a checkout)
REM    3. scripts\bootstrap.py: .venv + hash-pinned deps + install smoke
REM       (stdlib-only, tested; refuses Python < 3.12 with a named reason;
REM        never writes a bind other than 127.0.0.1; never asks for a cloud key)
REM    4. START.bat (unless you answer N within 15s)
REM
REM  Check-up any time:  .venv\Scripts\python scripts\doctor.py
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Nerva - Install

echo.
echo ============================================================
echo   NERVA - ONE-STEP INSTALL
echo ============================================================
echo.

set "REPO_URL=https://github.com/andrei649/jarvis-hub.git"

REM --- 1. Python 3.12+ -----------------------------------------
echo [1/3] Checking Python 3.12+...
set "PY="
where py >nul 2>&1 && ( py -3.12 --version >nul 2>&1 && set "PY=py -3.12" )
if "!PY!"=="" ( where py >nul 2>&1 && ( py -3 --version >nul 2>&1 && set "PY=py -3" ) )
if "!PY!"=="" ( where python >nul 2>&1 && set "PY=python" )
if "!PY!"=="" (
  echo   [MISSING] Python - trying to install via winget...
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo   [OK] Python installed. CLOSE this window and run INSTALL.bat AGAIN ^(PATH refresh^).
  ) else (
    echo   winget unavailable. Install Python 3.12+ manually ^(CHECK "Add Python to PATH"^):
    echo   https://www.python.org/downloads/
  )
  goto :end
)
!PY! --version
echo   [OK] Python found ^(the bootstrap enforces the 3.12 floor^).
echo.

REM --- 2. The code ---------------------------------------------
echo [2/3] Locating the code...
if exist "scripts\bootstrap.py" (
  echo   [OK] Inside the project folder.
) else (
  if exist "jarvis-hub\scripts\bootstrap.py" (
    echo   [OK] Project found in .\jarvis-hub
    cd jarvis-hub
  ) else (
    where git >nul 2>&1
    if !errorlevel! neq 0 (
      echo   [MISSING] git is needed to fetch the code. Install it ^(winget install Git.Git^)
      echo   or download the repo ZIP, unzip it, and double-click INSTALL.bat inside it.
      goto :end
    )
    echo   Cloning from GitHub...
    git clone --depth 1 %REPO_URL%
    if !errorlevel! neq 0 ( echo   [ERROR] Clone failed. Check your internet/repo access. & goto :end )
    cd jarvis-hub
  )
)
echo.

REM --- 3. Bootstrap: venv + locked deps + smoke ----------------
echo [3/3] Bootstrapping ^(.venv + hash-pinned dependencies + install smoke^)...
echo ------------------------------------------------------------
!PY! scripts\bootstrap.py %*
set "RC=!errorlevel!"
echo ------------------------------------------------------------
echo.
if not "!RC!"=="0" (
  echo   [FAILED] The bootstrap reported a named reason above. Fix it and re-run INSTALL.bat.
  echo   Check-up:  .venv\Scripts\python scripts\doctor.py
  goto :end
)

echo ============================================================
echo   [DONE] Nerva is installed.
echo   Start:      START.bat   ^(opens http://127.0.0.1:8080/v2 when ready^)
echo   Check-up:   .venv\Scripts\python scripts\doctor.py
echo   Phone/LAN:  docs\PHONE_ACCESS.md  ^(loopback only by default^)
echo   Update:     UPDATE.bat
echo ============================================================
echo.
choice /C YN /T 15 /D Y /M "Start Nerva now"
if !errorlevel!==1 (
  endlocal
  call START.bat
  exit /b
)
goto :end

REM ============================================================
:end
echo.
echo Press any key to close...
pause >nul
endlocal
