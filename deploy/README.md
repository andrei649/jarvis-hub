# Deployment & service templates

Run Nerva as a managed service that starts on boot, restarts on failure, and
stops **gracefully** (the H23.11 bounded shutdown drains in-flight requests before
exit). Pick your platform:

| Platform | Template | Guide |
|----------|----------|-------|
| Linux (systemd) | [`systemd/jarvis-hub.service`](systemd/jarvis-hub.service) + [`systemd/jarvis-hub.env`](systemd/jarvis-hub.env) | [systemd/README.md](systemd/README.md) |
| Windows (NSSM) | [`windows/install-service.ps1`](windows/install-service.ps1) | [windows/README.md](windows/README.md) |

Both wire the H23.11 operability knobs (`JARVIS_HOST` / `JARVIS_PORT` /
`JARVIS_SHUTDOWN_TIMEOUT` / `JARVIS_HOME`) and expose the health probes
`GET /healthz` (liveness) and `GET /readyz` (readiness) for an external monitor.

**Spelling of the pinned variables (RB-2).** `NERVA_<X>` is the preferred spelling of every
`JARVIS_<X>` variable, but both launchers *pin* the knobs above (and the runtime unit pins
`JARVIS_RUNTIME_LOG` / `JARVIS_RUNTIME_STATE`) under the `JARVIS_` spelling. Override a
pinned variable under that same spelling — in `jarvis.env`, or with the PowerShell
script's parameters. `NERVA_HOST` beside the unit's `JARVIS_HOST` is one variable set
twice with two values: the hub refuses to start and names it. That is exit status 78
from the hub and from the runtime supervisor, and neither unit (nor the NSSM service:
`AppExit 78 Exit`) restarts on it. Every boot guard's refusal is 78 too (H089): a
non-loopback bind without a token, an inbound channel nothing guards, a mistyped posture
flag, a hardened profile without its audit key, a refused profile name. A refusal that
comes from a `.env` file exits 1 and is retried once (the file may have been caught
mid-save); the same refusal at the next start is 78. Every variable the launcher
does not pin can be written either way. The full list is in
[`docs/FLAGS.md`](../docs/FLAGS.md#variable-names--nerva_x-and-jarvis_x-are-one-variable-rb-2).

For supported OS / Python / runtime versions and the upgrade/deprecation contract,
see [`docs/COMPATIBILITY.md`](../docs/COMPATIBILITY.md).

> **Containers / Docker:** `docker-compose.yml` (repo root) covers the WorldView
> side-stack. A first-class app container image + signed release artifacts are
> tracked under **H23.13** (release engineering) — not yet shipped here.
