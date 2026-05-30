@echo off
REM ============================================================
REM  JARVIS HUB - INSTALL (first-time setup, Windows 11)
REM  For a clean PC. Checks Python + Git, gets the code,
REM  builds the environment, installs deps, runs the tests.
REM  Just double-click. No prior knowledge needed.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title JARVIS HUB - Install

echo.
echo ============================================================
echo   JARVIS HUB - INSTALARE DE LA ZERO
echo ============================================================
echo.

set "REPO_URL=https://github.com/andrei649/jarvis-hub.git"

REM --- 1. Check Python ----------------------------------------
echo [1/5] Verific Python...
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py") else (
  where python >nul 2>&1
  if !errorlevel!==0 (set "PY=python") else (set "PY=")
)
if "%PY%"=="" (
  echo.
  echo   [LIPSESTE] Python nu este instalat.
  echo.
  echo   Incerc sa il instalez automat prin winget...
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo   [IMPORTANT] Inchide aceasta fereastra si ruleaza INSTALL.bat DIN NOU,
    echo   ca Windows sa recunoasca noul Python.
    goto :end
  ) else (
    echo   winget nu e disponibil. Instaleaza Python manual:
    echo   https://www.python.org/downloads/
    echo   ^>^> La instalare BIFEAZA "Add Python to PATH" ^<^<
    echo   Apoi ruleaza INSTALL.bat din nou.
    goto :end
  )
)
%PY% --version
echo   [OK] Python gasit.
echo.

REM --- 2. Check Git -------------------------------------------
echo [2/5] Verific Git...
where git >nul 2>&1
if %errorlevel% neq 0 (
  echo   [LIPSESTE] Git nu este instalat.
  winget --version >nul 2>&1
  if !errorlevel!==0 (
    echo   Incerc instalarea prin winget...
    winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
    echo.
    echo   [IMPORTANT] Inchide si ruleaza INSTALL.bat din nou.
    goto :end
  ) else (
    echo   Instaleaza Git manual: https://git-scm.com/download/win
    echo   Apoi ruleaza INSTALL.bat din nou.
    goto :end
  )
)
git --version
echo   [OK] Git gasit.
echo.

REM --- 3. Get the code ----------------------------------------
echo [3/5] Aduc codul proiectului...
if exist "serve.py" (
  echo   Sunt deja in folderul proiectului. Aduc ultimele modificari...
  git pull --rebase origin master
) else (
  if exist "jarvis-hub\serve.py" (
    echo   Proiectul exista deja in .\jarvis-hub - il actualizez...
    cd jarvis-hub
    git pull --rebase origin master
  ) else (
    echo   Clonez de pe GitHub...
    git clone %REPO_URL%
    if !errorlevel! neq 0 (
      echo   [EROARE] Clonarea a esuat. Verifica internetul / accesul la repo.
      goto :end
    )
    cd jarvis-hub
  )
)
echo.

REM --- 4. Virtual env + dependencies --------------------------
echo [4/5] Creez mediul Python si instalez dependentele...
if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --quiet --upgrade pip
"%VPY%" -m pip install --quiet -r requirements-beta.txt
"%VPY%" -m pip install --quiet tiktoken beautifulsoup4 psutil pytest-asyncio
echo   [OK] Dependente instalate.
echo.

REM --- 5. Run the tests ---------------------------------------
echo [5/5] Verific cu testele...
echo ------------------------------------------------------------
"%VPY%" -m pytest -q
set "TESTRC=%errorlevel%"
echo ------------------------------------------------------------
echo.

if "%TESTRC%"=="0" (
  echo ============================================================
  echo   [GATA] Instalare reusita!
  echo   Porneste aplicatia cu:  START.bat
  echo   Actualizeaza oricand cu: UPDATE.bat
  echo ============================================================
) else (
  echo   [ATENTIE] Instalarea s-a facut, dar unele teste au esuat.
  echo   Poti totusi incerca START.bat.
)

:end
echo.
echo Apasa o tasta pentru a inchide...
pause >nul
endlocal
