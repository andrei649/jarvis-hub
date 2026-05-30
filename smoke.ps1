# smoke.ps1 — Quick smoke test for Jarvis Hub
# Runs pytest and verifies the server starts.
param(
    [switch]$SkipServer
)

$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot

$failures = 0

Write-Host "===== pytest ========================" -ForegroundColor Cyan
python -m pytest tests/ -q --no-header
if ($LASTEXITCODE -ne 0) {
    $failures++
    Write-Host "FAIL: pytest exited with code $LASTEXITCODE" -ForegroundColor Red
} else {
    Write-Host "OK: all tests passed" -ForegroundColor Green
}

if (-not $SkipServer) {
    Write-Host "===== server smoke ==================" -ForegroundColor Cyan
    try {
        $proc = Start-Process python -ArgumentList "-m", "uvicorn", "agents.web:app", "--host", "127.0.0.1", "--port", "8080" -PassThru -NoNewWindow
        Start-Sleep -Seconds 5
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8080/" -UseBasicParsing -TimeoutSec 10
        if ($resp.StatusCode -ne 200) {
            $failures++
            Write-Host "FAIL: server returned $($resp.StatusCode)" -ForegroundColor Red
        } else {
            Write-Host "OK: server responded 200" -ForegroundColor Green
        }
    } catch {
        $failures++
        Write-Host "FAIL: server smoke test error: $_" -ForegroundColor Red
    } finally {
        if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
}

Pop-Location

Write-Host "===== result ========================" -ForegroundColor Cyan
if ($failures -eq 0) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures FAILURE(S)" -ForegroundColor Red
    exit 1
}
