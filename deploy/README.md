# Deployment & service templates

Run Jarvis Hub as a managed service that starts on boot, restarts on failure, and
stops **gracefully** (the H23.11 bounded shutdown drains in-flight requests before
exit). Pick your platform:

| Platform | Template | Guide |
|----------|----------|-------|
| Linux (systemd) | [`systemd/jarvis-hub.service`](systemd/jarvis-hub.service) + [`systemd/jarvis-hub.env`](systemd/jarvis-hub.env) | [systemd/README.md](systemd/README.md) |
| Windows (NSSM) | [`windows/install-service.ps1`](windows/install-service.ps1) | [windows/README.md](windows/README.md) |
| Linux, headless engine only (no dashboard) | [`systemd/jarvis-runtime-coordinator.service`](systemd/jarvis-runtime-coordinator.service) | [systemd/README.md](systemd/README.md#headless-engine-only-no-dashboard-jarvis-runtime-coordinatorservice) |
| Any platform, dev/CI | `make runtime-up` (`scripts/runtime_supervisor.py`) | [HANDOFF.md](../HANDOFF.md) |

Both `jarvis-hub.service` and the Windows service wire the H23.11 operability knobs
(`JARVIS_HOST` / `JARVIS_PORT` / `JARVIS_SHUTDOWN_TIMEOUT` / `JARVIS_HOME`) and expose
the health probes `GET /healthz` (liveness) and `GET /readyz` (readiness) for an
external monitor. The headless engine (`jarvis-runtime-coordinator.service` /
`make runtime-up`) has no HTTP surface — its liveness signal is the structured
run-log at `logs/runtime.jsonl` (one JSON line per cycle).

For supported OS / Python / runtime versions and the upgrade/deprecation contract,
see [`docs/COMPATIBILITY.md`](../docs/COMPATIBILITY.md).

> **Containers / Docker:** `docker-compose.yml` (repo root) covers the WorldView
> side-stack. A first-class app container image + signed release artifacts are
> tracked under **H23.13** (release engineering) — not yet shipped here.
