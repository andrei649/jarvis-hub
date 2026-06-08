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
  echo [EROARE] Python nu este instalat sau nu e in PATH.
  echo Descarca de la https://www.python.org/downloads/ si bifeaza
  echo "Add Python to PATH" la instalare.
  goto :end
)

REM --- 2. Pull latest from GitHub -----------------------------
echo [1/4] Aduc ultimele modificari de pe GitHub...
git pull --rebase origin main
if %errorlevel% neq 0 (
  echo.
  echo [ATENTIE] git pull a esuat. Poate ai modificari locale nesalvate.
  echo Ruleaza in terminal:  git status
  goto :end
)
echo.

REM --- 3. Virtual env + dependencies --------------------------
echo [2/4] Pregatesc mediul Python (.venv)...
if not exist ".venv\Scripts\python.exe" (
  echo     Creez mediul virtual prima data...
  %PY% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"

echo [3/5] Instalez dependentele JARVIS...
"%VPY%" -m pip install --quiet --upgrade pip
"%VPY%" -m pip install --quiet -r requirements-beta.txt
echo.

REM --- 4. WorldView: refresh dependinte Node (daca exista) ----
echo [4/5] WorldView: actualizez dependintele Node...
if exist "worldview\package.json" (
  where npm >nul 2>&1
  if !errorlevel!==0 (
    pushd worldview
    call npm install
    popd
    echo   [OK] WorldView actualizat.
  ) else (
    echo   [SKIP] npm negasit - sar peste WorldView ^(JARVIS e actualizat^).
  )
) else (
  echo   [SKIP] worldview lipseste in acest checkout.
)
echo.

REM --- 5. Run the tests ---------------------------------------
echo [5/5] Rulez testele...
echo ------------------------------------------------------------
"%VPY%" -m pytest -q
set "TESTRC=%errorlevel%"
echo ------------------------------------------------------------
echo.
if "%TESTRC%"=="0" (
  echo   [OK] Totul a trecut. Poti porni aplicatia cu START.bat
) else (
  echo   [ATENTIE] Unele teste au esuat ^(vezi mai sus^).
)

:end
echo.
echo Apasa o tasta pentru a inchide...
pause >nul
endlocal
