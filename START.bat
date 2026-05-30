@echo off
REM ============================================================
REM  JARVIS HUB - START  (Windows 11, double-click)
REM  Starts the server and opens the HUD in your browser.
REM  Run UPDATE.bat first if you want the latest version.
REM ============================================================
setlocal
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

echo Pornesc serverul pe http://127.0.0.1:8000
echo HUD:   http://127.0.0.1:8000/
echo Admin: http://127.0.0.1:8000/admin
echo.
echo (Lasa aceasta fereastra deschisa. Inchide-o ca sa opresti serverul.)
echo.

REM Open the browser once the server is listening (poll port 8000).
start "" /b powershell -NoProfile -Command "Write-Host 'Astept pornirea serverului...'; while ($true) { try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { Start-Process 'http://127.0.0.1:8000/'; break } } catch { Start-Sleep 3 } }"

"%VPY%" serve.py

echo.
echo Serverul s-a oprit.
pause >nul
endlocal
