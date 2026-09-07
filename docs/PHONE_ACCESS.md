# Phone / second-device access — the supported LAN path

> By default Nerva is **not reachable from a phone, by design**: `serve.py` binds
> `127.0.0.1`, and the guards below refuse anything else unless you make an explicit,
> token-gated decision. This page is that decision, written down — what each guard
> refuses, what you set, and what stays closed. The installer never does this for you.

## The three guards (what refuses what)

| guard | where | refuses | unless |
|---|---|---|---|
| `assert_safe_bind` | `agents/core/boot_guards.py`, run by `serve.py` and the app lifespan | **starting** with `JARVIS_HOST` set to a non-loopback address (`0.0.0.0`, a LAN IP) — the process exits with `Refusing to bind to non-loopback host …` | `JARVIS_USER_TOKEN` and/or `JARVIS_ADMIN_TOKEN` is set (authenticated), or `JARVIS_ALLOW_INSECURE_BIND=1` (acknowledged-insecure; not the path this page recommends) |
| `_user_guard` | `agents/web.py` — every user-facing route: `/chat`, memory, notes, code execution, the HUD's API | a request whose peer is **not** `127.0.0.1` / `::1` / `localhost` → **403** `user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access` | `JARVIS_USER_TOKEN` is set **and** the request carries `X-User-Token: <value>` (a valid `X-Admin-Token` also passes: admin ⊇ user). With the token set but missing/wrong → **401** |
| `_admin_guard` | `agents/web.py` — `/admin`, approvals, settings, exports | the same shape one tier up: non-localhost → 403 without `JARVIS_ADMIN_TOKEN`; wrong/missing token → 401 | `X-Admin-Token` matches |

Two consequences worth knowing before you start:

- Behind a reverse proxy the guards **fail closed**: when forwarding headers are
  present and `JARVIS_TRUSTED_PROXY` is unset, the client is treated as non-localhost,
  so the localhost exemption never applies and the token is required. Set
  `JARVIS_TRUSTED_PROXY=1` **only** for a proxy you control that populates
  `X-Forwarded-For`; then its first hop is used as the client address (for the
  localhost gate and for rate limiting).
- Unauthenticated network clients are rate-limited (`JARVIS_RATE_LIMIT`, 120/min per
  IP); a wrong-token attempt counts, so token guessing is throttled.

## Do this (LAN, same Wi-Fi)

1. **Mint a token** on the box (any long random string; keep it out of chat logs):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. **Set the bind and the token in the environment you start Nerva from** — not
   only in `.env`. The bind check (`assert_safe_bind`) runs in `serve.py` *before*
   the orchestrator loads `.env`, so a `JARVIS_HOST` line in `.env` is never seen by
   it and a token that lives only in `.env` cannot satisfy it either; the request
   guards do read `.env` late (`ENV-039`), which is why the token may *also* live
   there for day-to-day use.
   ```bash
   # Linux/macOS
   export JARVIS_HOST=0.0.0.0                 # or the box's LAN IP, e.g. 192.168.1.20
   export JARVIS_USER_TOKEN=<the value from step 1>
   # export JARVIS_ADMIN_TOKEN=<another value>   # only if you want approvals from the phone
   ```
   ```bat
   :: Windows (same window that will run START.bat)
   set JARVIS_HOST=0.0.0.0
   set JARVIS_USER_TOKEN=<the value from step 1>
   ```
   `python scripts/doctor.py` now reports `bind_is_loopback: non_loopback_with_token`
   — the same rule `assert_safe_bind` applies at boot, checked before you start
   (`non_loopback_without_token` means the boot would be refused).
3. **Restart** (`./start.sh` / `START.bat`). The boot log prints
   `[SECURITY] binding to non-loopback host … (authenticated)`.
4. **On the phone**, on the same network:
   - **Browser:** open `http://<box-LAN-IP>:8080/v2`. The first 401 prompts once for
     `X-User-Token`; the HUD remembers it (`localStorage` key `hud.user_token`).
   - **Mobile app** (`mobile/`): Settings → hub address `<box-LAN-IP>:8080` (scheme is
     added), user token = the same value; it is sent as `X-User-Token`. Add the admin
     token only if you want to approve actions from the phone (`X-Admin-Token`,
     admin-gated routes only). See `mobile/README.md`.

To go back to loopback-only: unset `JARVIS_HOST` and restart. The token can stay; with
a loopback bind it is simply not required from localhost.

## What stays closed even after this

- **The kernel's approval floor is unchanged.** Money, locks, security disablement and
  exposing private video never rise above the approval queue no matter which device
  asks; a phone with the *user* token can chat and read, and needs the *admin* token
  to approve.
- **Cleartext.** This is plain HTTP on your LAN. The mobile app allows cleartext to
  local networks on purpose; beyond a trusted LAN put TLS in front (a reverse proxy
  such as Caddy/Tailscale Serve) and keep the tokens.
- **Not the public internet.** Nothing here opens a port on your router. If you want
  Nerva off-LAN, use a private overlay (Tailscale/WireGuard) so the bind stays inside
  your network; port-forwarding `:8080` is not a supported topology.
- **No cloud hop is implied.** A phone talking to your box does not change which
  agents may use a cloud model; those stay per-agent opt-ins in Admin → settings.

## Rotation and recovery

Static env tokens are the bootstrap credential. Managed tokens (issued, rotated,
revoked, with TTLs) live in the token store and supersede them once rotated:

```bash
python -m agents.core.security.token_store issue  user  30     # 30-day user token, shown once
python -m agents.core.security.token_store rotate admin
python -m agents.core.security.token_store revoke all --revoke-env
python -m agents.core.security.token_store list
```

If every token is lost, that offline CLI on the box (filesystem access) is the root of
trust — there is no network recovery path, by design.

## Why this is documented and not automated

`install.sh` / `INSTALL.bat` / `scripts/bootstrap.py` never write a bind other than
`127.0.0.1` and never generate a token. Exposing the assistant to a network is an
owner decision with a blast radius (chat, memory, code execution), so it lives in a
page you read, not a flag an installer flips. `doctor` tells you which posture you are
in before you start; the guards tell you again at boot.
