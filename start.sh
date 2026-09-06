#!/usr/bin/env bash
# start.sh — launch Nerva (Linux/macOS). Mirrors START.bat.
#
#   ./start.sh              start on http://127.0.0.1:8080 and open the Command Center
#                           (/v2) in your browser once /readyz answers
#   ./start.sh --no-browser same, without opening a browser (also: NERVA_NO_BROWSER=1)
#   ./start.sh --doctor     run the install check-up (scripts/doctor.py) instead of starting
#
# WorldView (4D OSINT) and the Signal Layer are OPT-IN companions:
# start them with JARVIS_WORLDVIEW=1 / JARVIS_SIGNAL_LAYER=1.
# Serves the V2 cockpit HUD by default (set JARVIS_HUD=v1 for the legacy HUD).
# The bind stays loopback (127.0.0.1) — a phone or second device is a documented,
# token-gated decision: docs/PHONE_ACCESS.md.
set -uo pipefail
cd "$(dirname "$0")"

OPEN_BROWSER="${NERVA_NO_BROWSER:+0}"
OPEN_BROWSER="${OPEN_BROWSER:-1}"
for arg in "$@"; do
  case "$arg" in
    --no-browser) OPEN_BROWSER=0 ;;
    --doctor)
      if [ -x .venv/bin/python ]; then exec .venv/bin/python scripts/doctor.py; fi
      exec python3 scripts/doctor.py ;;
    *) echo "[WARN] unknown option: $arg" >&2 ;;
  esac
done

# --- WorldView (4D OSINT) — opt-IN with JARVIS_WORLDVIEW=1 ---
if [ "${JARVIS_WORLDVIEW:-0}" = "1" ] && [ -f worldview/package.json ]; then
  if command -v docker >/dev/null 2>&1 && command -v npm >/dev/null 2>&1 && [ -d worldview/node_modules ]; then
    echo "[WorldView] starting infra (TimescaleDB + Redis + Redpanda)…"
    if ( cd worldview && docker compose up -d ); then
      echo "[WorldView] starting API (:4000) and frontend (:3000) in the background…"
      ( cd worldview && nohup npm run dev:api      >/tmp/worldview-api.log      2>&1 & )
      ( cd worldview && nohup npm run dev:frontend >/tmp/worldview-frontend.log 2>&1 & )
      echo "[WorldView] UI at http://localhost:3000 (first build takes a bit). Logs: /tmp/worldview-*.log"
      echo "[WorldView] demo data: cd worldview && npm run db:seed"
    else
      echo "[WorldView] docker compose failed — is Docker running? Skipping WorldView."
    fi
  else
    echo "[WorldView] skipped (need Docker + Node, and 'cd worldview && npm install' once). Starting Nerva only."
  fi
fi

# --- Jarvis Signal Layer — opt-IN with JARVIS_SIGNAL_LAYER=1 ---
if [ "${JARVIS_SIGNAL_LAYER:-0}" = "1" ] && [ -f services/signal-layer/src/index.mjs ]; then
  if command -v node >/dev/null 2>&1; then
    export JARVIS_SIGNAL_LAYER_MODE="${JARVIS_SIGNAL_LAYER_MODE:-${JARVIS_WORLDVIEW_MODE:-replay}}"
    export SIGNAL_LAYER_HOST="${SIGNAL_LAYER_HOST:-127.0.0.1}"
    export SIGNAL_LAYER_PORT="${SIGNAL_LAYER_PORT:-8787}"
    export WORLDMONITOR_BASE_URL="${WORLDMONITOR_BASE_URL:-http://localhost:3100}"
    export WORLDMONITOR_MCP_URL="${WORLDMONITOR_MCP_URL:-http://localhost:3100/api/mcp}"
    echo "[Signal Layer] starting at http://127.0.0.1:${SIGNAL_LAYER_PORT}/healthz (mode=${JARVIS_SIGNAL_LAYER_MODE}). Logs: /tmp/jarvis-signal-layer.log"
    ( cd services/signal-layer && nohup node src/index.mjs >/tmp/jarvis-signal-layer.log 2>&1 & )
  else
    echo "[Signal Layer] skipped (Node 20+ required)."
  fi
fi

PYBIN=python3
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  PYBIN=python
else
  echo "[INFO] no .venv found — run ./install.sh first. Using system python3."
fi

# The V2 cockpit is the primary HUD going forward; override with JARVIS_HUD=v1 (legacy at /v1).
export JARVIS_HUD="${JARVIS_HUD:-v2}"
PORT="${JARVIS_PORT:-8080}"
URL="http://127.0.0.1:${PORT}/v2"

# Open the Command Center once /readyz answers (stdlib poll, loopback only; gives up
# after ~2 minutes so a failed boot never leaves a poller behind).
if [ "$OPEN_BROWSER" = "1" ]; then
  opener=""
  if command -v xdg-open >/dev/null 2>&1; then opener="xdg-open";
  elif command -v open >/dev/null 2>&1; then opener="open"; fi
  if [ -n "$opener" ]; then
    (
      "$PYBIN" - "$PORT" <<'PY' && "$opener" "$URL" >/dev/null 2>&1
import sys, time, urllib.request
port = sys.argv[1]
for _ in range(60):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2) as r:
            if r.status == 200:
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
    time.sleep(2)
raise SystemExit(1)
PY
    ) &
  fi
fi

echo "Starting Nerva at http://127.0.0.1:${PORT}/  (HUD=$JARVIS_HUD; Command Center at ${URL}; Ctrl-C to stop)"
exec "$PYBIN" serve.py
