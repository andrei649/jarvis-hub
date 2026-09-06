#!/usr/bin/env bash
# install.sh — Nerva one-step native install (Linux/macOS).
#
# Two ways to run it, same result — a venv with the hash-pinned dependency set,
# a passed install smoke, and the Command Center open on http://127.0.0.1:8080/v2:
#
#   ./install.sh                                   # from a checkout
#   curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash
#                                                  # hosted one-liner: clones into $NERVA_DIR
#                                                  # (default ~/nerva) and installs there
#
# Options (forwarded to scripts/bootstrap.py unless noted):
#   --dev         also run the full offline pytest suite after the smoke (wrapper-only)
#   --no-start    do not launch Nerva at the end (wrapper-only; also implied when
#                 stdout is not a terminal, e.g. CI)
#   --skip-smoke  venv + deps only            --unlocked  install from requirements-beta.txt
#
# Everything that matters happens in scripts/bootstrap.py (stdlib-only, tested):
# Python >= 3.12 floor with a named refusal, idempotent .venv, `pip --require-hashes`
# from requirements-beta.lock, loopback-only runtime detection (Ollama/LM Studio),
# the install smoke. This wrapper only finds an interpreter and the checkout.
# It never writes a bind other than 127.0.0.1 and never asks for a cloud key.
#
# WorldView (4D OSINT) stays a separate, OPT-IN companion: JARVIS_WORLDVIEW=1 ./install.sh
set -euo pipefail

NERVA_DIR="${NERVA_DIR:-$HOME/nerva}"
REPO_URL="${NERVA_REPO_URL:-https://github.com/andrei649/jarvis-hub.git}"

DEV=0
START=1
FORWARD=()
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    --no-start) START=0 ;;
    *) FORWARD+=("$arg") ;;
  esac
done
[ -t 1 ] || START=0

echo "============================================================"
echo "  Nerva — install (Linux/macOS)"
echo "============================================================"

# 0. Find the checkout: next to this script, in the current directory, or clone it.
checkout=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/scripts/bootstrap.py" ]; then
  checkout="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elif [ -f "./scripts/bootstrap.py" ]; then
  checkout="$(pwd)"
fi
if [ -z "$checkout" ]; then
  if ! command -v git >/dev/null 2>&1; then
    echo "[MISSING] git is required for the one-line install (or download the repo and run ./install.sh inside it)." >&2
    exit 1
  fi
  if [ -d "$NERVA_DIR/.git" ]; then
    echo "[0/3] Updating the checkout in $NERVA_DIR…"
    git -C "$NERVA_DIR" pull --ff-only
  else
    echo "[0/3] Cloning into $NERVA_DIR…"
    git clone --depth 1 "$REPO_URL" "$NERVA_DIR"
  fi
  checkout="$NERVA_DIR"
fi
cd "$checkout"

# 1. Interpreter: the first candidate that meets the 3.12 floor; otherwise the newest
#    we found, so scripts/bootstrap.py prints the named refusal (python_too_old:…).
PY=""
FALLBACK=""
for cand in python3.13 python3.12 python3 python; do
  command -v "$cand" >/dev/null 2>&1 || continue
  [ -n "$FALLBACK" ] || FALLBACK="$cand"
  if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ] && [ -z "$FALLBACK" ]; then
  echo "[MISSING] No python found. Install Python 3.12+ (https://www.python.org/downloads/) and re-run." >&2
  exit 1
fi
PY="${PY:-$FALLBACK}"
echo "[1/3] Using $PY ($("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"

# 2. WorldView (4D OSINT) — a separate companion stack, OPT-IN via JARVIS_WORLDVIEW=1.
if [ "${JARVIS_WORLDVIEW:-0}" = "1" ] && [ -f worldview/package.json ]; then
  echo "[2/3] WorldView setup (opt-in)…"
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
    fi
  else
    echo "      [SKIP] Node/npm not found (need Node 20+) — WorldView not set up. Nerva works without it."
  fi
  command -v docker >/dev/null 2>&1 || echo "      [NOTE] Docker not found — WorldView infra needs it."
else
  echo "[2/3] WorldView: not requested (opt-in: JARVIS_WORLDVIEW=1 ./install.sh)."
fi

# 3. The install itself — stdlib-only, exits non-zero with a named reason on failure.
echo "[3/3] Bootstrapping (venv + locked deps + smoke)…"
"$PY" scripts/bootstrap.py "${FORWARD[@]+"${FORWARD[@]}"}"

if [ "$DEV" = "1" ]; then
  echo "[dev] Running the full offline test suite…"
  .venv/bin/python -m pytest -q || echo "[WARN] some tests failed — you can still ./start.sh" >&2
fi

if [ "$START" = "1" ]; then
  echo "Starting Nerva now (Ctrl-C to stop; next time: ./start.sh)…"
  exec ./start.sh
fi
