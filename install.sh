#!/usr/bin/env bash
# install.sh — Jarvis Hub one-command setup for Linux/macOS.
# Mirrors INSTALL.bat: creates a venv, installs deps, runs the tests.
# Then start with ./start.sh  (or: source .venv/bin/activate && python serve.py)
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  JARVIS HUB — install (Linux/macOS)"
echo "============================================================"

# 1. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  echo "[MISSING] python3 not found. Install Python 3.12+ and re-run." >&2
  exit 1
fi
echo "[1/3] Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 2. venv + deps (one install — full feature set)
echo "[2/3] Creating .venv and installing dependencies…"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-beta.txt
echo "      dependencies installed."

# 3. Verify with the offline test suite
echo "[3/3] Running the offline test suite…"
if python -m pytest -q; then
  echo "============================================================"
  echo "  Done. Start the server with:   ./start.sh"
  echo "  then open  http://127.0.0.1:8080/"
  echo "============================================================"
else
  echo "[WARN] some tests failed — you can still try: ./start.sh" >&2
fi
