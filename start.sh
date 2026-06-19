#!/usr/bin/env bash
# start.sh — launch Jarvis Hub (Linux/macOS). Mirrors START.bat.
# Also auto-starts WorldView (4D OSINT) unless JARVIS_WORLDVIEW=0 and
# the Jarvis Signal Layer unless JARVIS_SIGNAL_LAYER=0.
# Serves the V2 cockpit HUD by default (set JARVIS_HUD=v1 for the legacy HUD).
set -uo pipefail
cd "$(dirname "$0")"

# --- WorldView (4D OSINT) — optional, opt-out with JARVIS_WORLDVIEW=0 ---
if [ "${JARVIS_WORLDVIEW:-1}" != "0" ] && [ -f worldview/package.json ]; then
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
    echo "[WorldView] skipped (need Docker + Node, and 'cd worldview && npm install' once). Starting JARVIS only."
  fi
fi

# --- Jarvis Signal Layer — optional, opt-out with JARVIS_SIGNAL_LAYER=0 ---
if [ "${JARVIS_SIGNAL_LAYER:-1}" != "0" ] && [ -f services/signal-layer/src/index.mjs ]; then
  if command -v node >/dev/null 2>&1; then
    export JARVIS_SIGNAL_LAYER_MODE="${JARVIS_SIGNAL_LAYER_MODE:-${JARVIS_WORLDVIEW_MODE:-replay}}"
    export SIGNAL_LAYER_HOST="${SIGNAL_LAYER_HOST:-0.0.0.0}"
    export SIGNAL_LAYER_PORT="${SIGNAL_LAYER_PORT:-8787}"
    export WORLDMONITOR_BASE_URL="${WORLDMONITOR_BASE_URL:-http://localhost:3100}"
    export WORLDMONITOR_MCP_URL="${WORLDMONITOR_MCP_URL:-http://localhost:3100/api/mcp}"
    echo "[Signal Layer] starting at http://127.0.0.1:${SIGNAL_LAYER_PORT}/healthz (mode=${JARVIS_SIGNAL_LAYER_MODE}). Logs: /tmp/jarvis-signal-layer.log"
    ( cd services/signal-layer && nohup node src/index.mjs >/tmp/jarvis-signal-layer.log 2>&1 & )
  else
    echo "[Signal Layer] skipped (Node 20+ required)."
  fi
fi

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[INFO] no .venv found — run ./install.sh first. Using system python."
fi

# The V2 cockpit is the primary HUD going forward; override with JARVIS_HUD=v1 (legacy at /v1).
export JARVIS_HUD="${JARVIS_HUD:-v2}"

echo "Starting Jarvis Hub at http://127.0.0.1:8080/  (HUD=$JARVIS_HUD; Ctrl-C to stop)"
exec python serve.py
