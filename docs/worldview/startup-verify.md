# Startup Verification — World Intelligence launchers

_Lane: `feature/world-intelligence-startup-verify`. Verifies the demo launch path without
changing launcher behavior. Run against `feature/jarvis-signal-layer`._

This lane validates that `START.bat` / `start.sh` bring up the World Intelligence demo with the
correct port boundaries and opt-outs, and that the Signal Layer replay path actually serves data.

## Validation matrix

| Check | Result | Evidence |
|---|---|---|
| `start.sh` syntax | ✅ pass | `bash -n start.sh` exits 0 |
| `START.bat` structure | ✅ pass | balanced `setlocal`/`endlocal`/`exit /b`; subroutines (`:start_worldview`, `:start_signal_layer`) after `exit /b`, each closing `goto :eof` |
| `JARVIS_SIGNAL_LAYER=0` opt-out | ✅ pass | `start.sh` guards on `[ "${JARVIS_SIGNAL_LAYER:-1}" != "0" ]`; `START.bat` skips via `if /I "%JARVIS_SIGNAL_LAYER%"=="0"` |
| `JARVIS_WORLDVIEW=0` opt-out | ✅ pass | symmetric guard in both launchers |
| Mode fallback chain | ✅ pass | `JARVIS_SIGNAL_LAYER_MODE` → deprecated `JARVIS_WORLDVIEW_MODE` → `replay`, in both launchers |
| WorldView ports `:3000` / `:4000` | ✅ pass | API `:4000`, frontend `:3000` (start.sh L14–17; START.bat L109) |
| Signal Layer port `:8787` | ✅ pass | `SIGNAL_LAYER_PORT` default `8787` in both |
| WorldMonitor `:3100` optional only | ✅ pass | referenced as `WORLDMONITOR_BASE_URL`/`MCP_URL` for live mode; **never auto-started** |
| Jarvis Hub port `:8080` | ✅ pass | hub served on `:8080` in both |

## Signal Layer replay boot (runtime)

Booted the service directly (`JARVIS_SIGNAL_LAYER_MODE=replay node src/index.mjs`) and exercised the
demo endpoints — no WorldMonitor, no API keys, no network:

| Endpoint | Result |
|---|---|
| `GET /healthz` | `ok: true`, `mode: replay`, provider `worldmonitor` (fixture) `status: ok` |
| `GET /briefs/world` | returns `Global Intelligence Brief` (deterministic fixture) |
| `GET /signals?limit=8&relevantOnly=true` | `count: 6`, provider `worldmonitor` |
| `GET /assessments/country/RO` | HTTP 200 |

Replay mode is deterministic and demo-safe.

## Notes / known items (not changed in this lane)

- **`START.bat` venv/python detection** (lines ~33–34): `if %errorlevel%==0` is read inside a
  parenthesized `else` block without `enabledelayedexpansion`, so it expands at parse time (stale
  errorlevel) — the `py`-launcher branch may be taken regardless of whether `py` exists. Pre-existing,
  unrelated to the Signal Layer; flagged for a future launcher-hardening pass (a `where py && (...) || (...)`
  form avoids the errorlevel entirely).
- **`SIGNAL_LAYER_HOST` defaults to `0.0.0.0`** in both launchers and `config.mjs`. Combined with the
  service having no auth and CORS `*`, the replay service is reachable from the LAN. Low risk in replay
  (ephemeral state, no secrets) but should be tightened to `127.0.0.1` (or add token validation) before
  live mode — tracked against PR #248 review.

## Claims this lane supports

- Replay mode is deterministic and demo-safe.
- Launchers keep WorldView (`:3000`/`:4000`), Signal Layer (`:8787`), and WorldMonitor (`:3100`,
  optional/live only) on separate ports.
- WorldMonitor is **not** started automatically; it is a separate sidecar for live mode only.
