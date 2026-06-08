#!/usr/bin/env bash
# install.sh — Jarvis Hub one-command setup for Linux/macOS.
# Mirrors INSTALL.bat: Python venv + deps + tests, PLUS WorldView (4D OSINT):
# checks Node 20+, scaffolds .env files, npm install. Then start with ./start.sh
set -uo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  JARVIS HUB + WorldView — install (Linux/macOS)"
echo "============================================================"

# 1. Python 3.12+
if ! command -v python3 >/dev/null 2>&1; then
  echo "[MISSING] python3 not found. Install Python 3.12+ and re-run." >&2
  exit 1
fi
echo "[1/5] Python $(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# 2. venv + JARVIS dependencies (one install — full feature set)
echo "[2/5] Creating .venv and installing JARVIS dependencies…"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-beta.txt
echo "      dependencies installed."

# 3. WorldView (4D OSINT) — optional; soft-skip if tooling is absent so JARVIS still installs
echo "[3/5] WorldView setup (optional)…"
if [ -f worldview/package.json ]; then
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
    if [ "${node_major:-0}" -lt 20 ]; then
      echo "      [WARN] Node $(node -v 2>/dev/null) is < 20 — WorldView needs Node 20+. Skipping npm install."
    else
      [ -f worldview/.env ] || cp worldview/.env.example worldview/.env
      [ -f worldview/backend-api/.env ] || cp worldview/backend-api/.env.example worldview/backend-api/.env
      [ -f worldview/frontend/.env.local ] || cp worldview/frontend/.env.local.example worldview/frontend/.env.local
      echo "      .env files ready; installing Node deps (a few minutes the first time)…"
      ( cd worldview && npm install ) || echo "      [WARN] npm install reported errors — see output above."
      echo "      WorldView ready."
    fi
  else
    echo "      [SKIP] Node/npm not found (need Node 20+) — WorldView not set up. JARVIS works without it."
  fi
  command -v docker >/dev/null 2>&1 || echo "      [NOTE] Docker not found — WorldView infra needs it; install Docker to run WorldView."
else
  echo "      [SKIP] worldview/ not present in this checkout."
fi

# 4. Verify JARVIS with the offline test suite
echo "[4/5] Running the JARVIS offline test suite…"
if python -m pytest -q; then
  TESTS_OK=1
else
  TESTS_OK=0
  echo "[WARN] some tests failed — you can still try: ./start.sh" >&2
fi

# 5. Done
echo "[5/5] Done. (tests ok: ${TESTS_OK})"
echo "============================================================"
echo "  Start everything:    ./start.sh                 (JARVIS :8080 + WorldView :3000)"
echo "  JARVIS only:         JARVIS_WORLDVIEW=0 ./start.sh"
echo "  WorldView demo data: cd worldview && npm run db:seed"
echo "  then open  http://127.0.0.1:8080/   (V2 cockpit; legacy HUD at /v1)"
echo "============================================================"
