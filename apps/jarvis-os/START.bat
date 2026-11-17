@echo off
setlocal
title ANDREI OS - J.A.R.V.I.S. Second Brain ^& 3D Workshop
cd /d "%~dp0"

if not defined JARVIS_PORT set "JARVIS_PORT=4719"

echo.
echo   ============================================================
echo    ANDREI OS - J.A.R.V.I.S. Second Brain ^& 3D Workshop
echo    Starting local server at http://localhost:%JARVIS_PORT% ...
echo   ============================================================
echo.

start "" http://localhost:%JARVIS_PORT%

rem 1) uv: brings its own Python 3.12, so it works even when python.exe is
rem    only the Microsoft Store stub.
where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    uv run --no-project --python 3.12 python server.py
    goto :done
)

rem 2) The py launcher - only if it can actually start a Python 3.
py -3 -c "import sys" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 server.py
    goto :done
)

rem 3) Plain python - the Store stub fails this probe instead of running.
python -c "import sys" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python server.py
    goto :done
)

echo   No working Python found. Install uv (https://docs.astral.sh/uv/) or
echo   Python 3.9+ from https://www.python.org/downloads/ and run START.bat again.

:done
pause
