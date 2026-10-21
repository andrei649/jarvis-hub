#!/usr/bin/env bash
# uninstall.sh — remove Nerva's installer-created software footprint (Linux/macOS).
# Mirrors install.sh's steps in reverse: removes .venv/ + WorldView's node_modules/ and
# generated env files. Your DATA is never touched — memory_logs/ (or $JARVIS_HOME) is
# untouched by default; pass --purge-data to also erase it (backup-first, irreversible,
# and only after you type the data folder's name back — or pass --yes-purge=<absolute data-root path>).
#
# Usage:
#   ./uninstall.sh --dry-run [--gui] [--purge-data]   # print what WOULD be removed; remove nothing
#   ./uninstall.sh --gui-summary             # JSON probe: is the desktop app installed, where
#   ./uninstall.sh --confirm                 # remove the software footprint only
#   ./uninstall.sh --confirm --gui           # also remove the desktop app
#   ./uninstall.sh --confirm --gui-only      # remove ONLY the desktop app (engine + data stay)
#   ./uninstall.sh --confirm --purge-data     # also erase your data (backup-first, typed confirmation)
set -uo pipefail
cd "$(dirname "$0")"

CONFIRM=0
PURGE_DATA=0
DRY_RUN=0
GUI=0
GUI_ONLY=0
GUI_SUMMARY=0
YES_PURGE=""
for arg in "$@"; do
  case "$arg" in
    --confirm) CONFIRM=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --gui) GUI=1 ;;
    --gui-only) GUI_ONLY=1 ;;
    --gui-summary) GUI_SUMMARY=1 ;;
    --purge-data) PURGE_DATA=1 ;;
    --yes-purge=*) YES_PURGE="${arg#--yes-purge=}" ;;
    --no-backup) NO_BACKUP=1 ;;
    # Refuse, never just warn: a mistyped "--dryrun --confirm" must not become a real uninstall.
    *) echo "[ERROR] unknown option: $arg — nothing was removed" >&2; exit 2 ;;
  esac
done

echo "============================================================"
echo "  JARVIS HUB — uninstall (Linux/macOS)"
echo "============================================================"

if [ "$CONFIRM" != "1" ] && [ "$DRY_RUN" != "1" ] && [ "$GUI_SUMMARY" != "1" ]; then
  echo "This removes: .venv/, worldview/node_modules/, and WorldView's generated .env files."
  echo "Your data (memory_logs/ or \$JARVIS_HOME) is NOT touched unless you also pass --purge-data."
  echo
  echo "Preview first:                     ./uninstall.sh --dry-run"
  echo "Re-run with --confirm to proceed:  ./uninstall.sh --confirm"
  echo "  add --gui to also remove the desktop app (or --gui-only to remove just the desktop app)"
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

if [ "$GUI_SUMMARY" = "1" ]; then
  ARGS=(--gui-summary)
elif [ "$DRY_RUN" = "1" ]; then
  ARGS=(--dry-run)
else
  ARGS=(--confirm)
fi
[ "$GUI" = "1" ] && ARGS+=(--gui)
[ "$GUI_ONLY" = "1" ] && ARGS+=(--gui-only)
[ "$PURGE_DATA" = "1" ] && ARGS+=(--purge-data)
[ -n "$YES_PURGE" ] && ARGS+=("--yes-purge=$YES_PURGE")
[ "${NO_BACKUP:-0}" = "1" ] && ARGS+=(--no-backup)

"$PY" -m agents.core.uninstall "${ARGS[@]}"
RC=$?

if [ "$GUI_SUMMARY" = "1" ]; then
  exit "$RC"
fi
if [ "$DRY_RUN" = "1" ]; then
  echo "============================================================"
  echo "  Dry run — nothing was removed. Re-run with --confirm to proceed."
  echo "============================================================"
  exit "$RC"
fi

echo "============================================================"
if [ "$RC" = "0" ] && [ "$GUI_ONLY" = "1" ]; then
  echo "  Done. The desktop app has been removed; the engine and your data are untouched."
elif [ "$RC" = "0" ]; then
  echo "  Done. Nerva's software footprint has been removed."
  echo "  The repo checkout itself (source files) is left in place — delete this"
  echo "  folder yourself if you're removing Nerva entirely."
else
  echo "  [WARN] uninstall reported problems — see the messages above (the JSON report, or the module's refusal/error)."
fi
echo "============================================================"
exit "$RC"
