#!/usr/bin/env bash
# uninstall.sh — remove Nerva's installer-created software footprint (Linux/macOS).
# Mirrors install.sh's steps in reverse: removes .venv/ + WorldView's node_modules/ and
# generated env files. Your DATA is never touched — memory_logs/ (or $JARVIS_HOME) is
# untouched by default; pass --purge-data to also erase it (backup-first, irreversible).
#
# Usage:
#   ./uninstall.sh --confirm                 # remove the software footprint only
#   ./uninstall.sh --confirm --purge-data     # also erase your data (backup-first)
set -uo pipefail
cd "$(dirname "$0")"

CONFIRM=0
PURGE_DATA=0
for arg in "$@"; do
  case "$arg" in
    --confirm) CONFIRM=1 ;;
    --purge-data) PURGE_DATA=1 ;;
    --no-backup) NO_BACKUP=1 ;;
    *) echo "[WARN] unknown option: $arg" >&2 ;;
  esac
done

echo "============================================================"
echo "  JARVIS HUB — uninstall (Linux/macOS)"
echo "============================================================"

if [ "$CONFIRM" != "1" ]; then
  echo "This removes: .venv/, worldview/node_modules/, and WorldView's generated .env files."
  echo "Your data (memory_logs/ or \$JARVIS_HOME) is NOT touched unless you also pass --purge-data."
  echo
  echo "Re-run with --confirm to proceed:  ./uninstall.sh --confirm"
  echo "  add --purge-data to also erase your data (backup-first, irreversible)"
  exit 2
fi

# Prefer the SYSTEM python3 (install.sh required it to create .venv/ in the first
# place, so it's guaranteed present) over .venv/bin/python — the uninstall module
# removes .venv/ itself, and running it from the interpreter it's about to delete
# is unnecessary risk when a system interpreter is right there.
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
else
  echo "[ERROR] no python found (python3 or .venv/bin/python) — cannot run the uninstall module." >&2
  exit 1
fi

ARGS=(--confirm)
[ "$PURGE_DATA" = "1" ] && ARGS+=(--purge-data)
[ "${NO_BACKUP:-0}" = "1" ] && ARGS+=(--no-backup)

"$PY" -m agents.core.uninstall "${ARGS[@]}"
RC=$?

echo "============================================================"
if [ "$RC" = "0" ]; then
  echo "  Done. Nerva's software footprint has been removed."
  echo "  The repo checkout itself (source files) is left in place — delete this"
  echo "  folder yourself if you're removing Nerva entirely."
else
  echo "  [WARN] uninstall reported problems — see the JSON report above."
fi
echo "============================================================"
exit "$RC"
