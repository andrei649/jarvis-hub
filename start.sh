#!/usr/bin/env bash
# start.sh — launch the Jarvis Hub server (Linux/macOS). Mirrors START.bat.
set -euo pipefail
cd "$(dirname "$0")"

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[INFO] no .venv found — run ./install.sh first. Using system python."
fi

echo "Starting Jarvis Hub at http://127.0.0.1:8080/  (Ctrl-C to stop)"
exec python serve.py
