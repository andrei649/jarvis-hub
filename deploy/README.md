# Deployment & service templates

Run Jarvis Hub as a managed service that starts on boot, restarts on failure, and
stops **gracefully** (the H23.11 bounded shutdown drains in-flight requests before
exit). Pick your platform:

| Platform | Template | Guide |
|----------|----------|-------|
| Linux (systemd) | [`systemd/jarvis-hub.service`](systemd/jarvis-hub.service) + [`systemd/jarvis-hub.env`](systemd/jarvis-hub.env) | [systemd/README.md](systemd/README.md) |
| Windows (NSSM) | [`windows/install-service.ps1`](windows/install-service.ps1) | [windows/README.md](windows/README.md) |

Both wire the H23.11 operability knobs (`JARVIS_HOST` / `JARVIS_PORT` /
`JARVIS_SHUTDOWN_TIMEOUT` / `JARVIS_HOME`) and expose the health probes
`GET /healthz` (liveness) and `GET /readyz` (readiness) for an external monitor.

For supported OS / Python / runtime versions and the upgrade/deprecation contract,
see [`docs/COMPATIBILITY.md`](../docs/COMPATIBILITY.md).

> **Containers / Docker:** `docker-compose.yml` (repo root) covers the WorldView
> side-stack. A first-class app container image + signed release artifacts are
> tracked under **H23.13** (release engineering) — not yet shipped here.
