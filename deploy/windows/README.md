# Running Jarvis Hub as a Windows service

Windows has no native "host this console app as a resilient service" primitive,
so we use **NSSM** (the Non-Sucking Service Manager) — the standard approach. It
auto-starts the hub on boot, restarts it on crash, and stops it **gracefully**
by sending Ctrl-C (→ SIGINT → uvicorn drains in-flight requests within
`JARVIS_SHUTDOWN_TIMEOUT`, then exits — see H23.11).

## Prerequisites

- Jarvis installed with its venv: `INSTALL.bat` (creates `.venv\`).
- NSSM on PATH: `winget install NSSM` (or `choco install nssm`, or grab `nssm.exe`
  from <https://nssm.cc/download>).
- An **elevated** PowerShell (Run as Administrator).

## Install

```powershell
# from the repo root, elevated:
.\deploy\windows\install-service.ps1 `
    -InstallRoot C:\jarvis-hub `
    -DataRoot    C:\ProgramData\jarvis-hub
```

This registers the `JarvisHub` service (auto-start), sets the operability env
(`JARVIS_HOST`/`JARVIS_PORT`/`JARVIS_SHUTDOWN_TIMEOUT`/`JARVIS_HOME`), wires a
graceful Ctrl-C stop, and starts it.

## Operate

```powershell
Get-Service JarvisHub
nssm status JarvisHub
Restart-Service JarvisHub
Stop-Service JarvisHub          # graceful: drains, then exits
```

## In-place restore (H010)

An approved `nerva backup restore` is staged and the hub restarts itself to apply it
before any store opens. Under this service the hub exits with code **75** after it has
drained; NSSM (`AppExit Default Restart`, `AppRestartDelay 5000`) starts it again and that
boot applies the restore. A clean exit (code 0, `Stop-Service`) is not restarted
(`AppExit 0 Exit`). The script sets `NERVA_SERVICE_WRAPPER=nssm` so serve.py knows it runs
under NSSM; **a service installed before this marker existed has no self-restart** — the
approval answers `restart: "manual"`, `nerva backup list` says "restart the hub/service to
apply it before <expires_at>", and the jarvis-runtime coordinator (if you run one) stays
paused for `JARVIS_RUNTIME_RESTORE_GRACE_SECONDS`. Re-run `install-service.ps1` once to add
the marker, or `Restart-Service JarvisHub` after each approved restore.

The packaged `nerva.exe` (Start Menu) and `python serve.py` in a terminal restart by
starting a successor in a new console and exiting; the successor waits for the old
process to be gone (at most `JARVIS_RESTART_PREDECESSOR_WAIT_SECONDS`, default 60) before
it applies the restore.

## Uninstall

```powershell
.\deploy\windows\install-service.ps1 -Uninstall
```

## Health check

```powershell
curl http://127.0.0.1:8080/readyz   # 200 once loaded, 503 while starting
```

> Default bind is loopback. To expose off-loopback, pass `-BindHost` **and**
> configure an auth token (or set `JARVIS_ALLOW_INSECURE_BIND=1`) — otherwise the
> app refuses to boot (fail-closed, H23.11). Prefer a reverse proxy with TLS.
