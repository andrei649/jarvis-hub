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

The unit is `Type=notify` (H283): the hub sends `READY=1` to systemd once the
orchestrator and its agents are loaded (the moment `/readyz` would answer 200), so
`systemctl start jarvis-hub` returns when it can serve, and units ordered
`After=jarvis-hub.service` wait for that. It feeds systemd's watchdog
(`WatchdogSec=60`) with `WATCHDOG=1` every 30 s from its event loop: if the loop hangs,
the pings stop and systemd restarts the hub (`Restart=on-failure`). On stop it sends
`STOPPING=1` before draining. `systemctl status jarvis-hub` shows its `STATUS=` line.
Outside systemd (no `NOTIFY_SOCKET`) none of this runs.

For a monitor outside systemd, the probes still work:

```bash
curl -fsS http://127.0.0.1:8080/readyz >/dev/null || systemctl restart jarvis-hub
```

To tell the model about the machine it runs on (a proxy, how credentials are handled
here, where the shared drives are), set `JARVIS_ENVIRONMENT_HINT` in the env file, with
`\n` for a line break. It is given to every agent as a description of the machine, not
as instructions, at most 2,000 characters.

## Notes

- The unit is **hardened** (`ProtectSystem=strict`, `NoNewPrivileges`, restricted
  address families, etc.). If you relocate `JARVIS_HOME`, add it to `ReadWritePaths=`.
- Default bind is loopback. To expose it, set `JARVIS_HOST` **and** provide an auth
  token (or `JARVIS_ALLOW_INSECURE_BIND=1`) — otherwise the app refuses to boot
  (fail-closed, H23.11). Prefer a reverse proxy (TLS) over a raw off-loopback bind.
