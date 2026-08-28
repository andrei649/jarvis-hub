# Running Jarvis Hub as a Linux service (systemd)

`jarvis-hub.service` runs the hub under systemd so it starts on boot, restarts on
failure, and stops **gracefully** (SIGTERM → uvicorn drains in-flight requests
within `JARVIS_SHUTDOWN_TIMEOUT`, then exits — see H23.11). Logs go to the journal.

## Prerequisites

- Jarvis installed with its venv (`./install.sh` → `.venv/`), e.g. at `/opt/jarvis-hub`.
- A dedicated unprivileged user (recommended): `sudo useradd --system --home /var/lib/jarvis-hub --create-home jarvis`.

## Install

```bash
# 1. Edit the unit for your install: User/Group, WorkingDirectory, ExecStart path.
sudoedit /etc/systemd/system/jarvis-hub.service     # or cp from deploy/systemd/ first
sudo cp deploy/systemd/jarvis-hub.service /etc/systemd/system/

# 2. (optional) per-host overrides — tokens, JARVIS_HOME, off-loopback bind, etc.
sudo mkdir -p /etc/jarvis-hub
sudo cp deploy/systemd/jarvis-hub.env /etc/jarvis-hub/jarvis.env
sudoedit /etc/jarvis-hub/jarvis.env

# 3. ensure the data root is writable by the service user
sudo install -d -o jarvis -g jarvis /var/lib/jarvis-hub

# 4. enable + start
sudo systemctl daemon-reload
sudo systemctl enable --now jarvis-hub
```

## Operate

```bash
systemctl status jarvis-hub
journalctl -u jarvis-hub -f          # live logs
sudo systemctl restart jarvis-hub
sudo systemctl stop jarvis-hub       # graceful: drains, then exits
```

## Uninstall

```bash
sudo systemctl disable --now jarvis-hub
sudo rm /etc/systemd/system/jarvis-hub.service
sudo rm -rf /etc/jarvis-hub
sudo systemctl daemon-reload
```

This removes the service registration only — it does not touch `/var/lib/jarvis-hub`
(or wherever you pointed `JARVIS_HOME`), the dedicated service user, or the install
directory's `.venv/`. For those: `./uninstall.sh` (software footprint; add `--purge-data`
to also erase your data) from the install directory, then remove the directory itself and
`sudo userdel jarvis` if you created the dedicated user.

## Health checks

The hub exposes machine-facing probes (H23.11) a monitor can poll:

- `GET /healthz` → `200` while the process serves (liveness).
- `GET /readyz`  → `200` once the orchestrator + agents are loaded, `503` while starting.

A simple external watchdog (cron/timer or your monitoring stack):

```bash
curl -fsS http://127.0.0.1:8080/readyz >/dev/null || systemctl restart jarvis-hub
```

> systemd's built-in `WatchdogSec` needs `sd_notify` from the app, which the hub
> does not emit — use the `/readyz` curl check above instead.

## Notes

- The unit is **hardened** (`ProtectSystem=strict`, `NoNewPrivileges`, restricted
  address families, etc.). If you relocate `JARVIS_HOME`, add it to `ReadWritePaths=`.
- Default bind is loopback. To expose it, set `JARVIS_HOST` **and** provide an auth
  token (or `JARVIS_ALLOW_INSECURE_BIND=1`) — otherwise the app refuses to boot
  (fail-closed, H23.11). Prefer a reverse proxy (TLS) over a raw off-loopback bind.
