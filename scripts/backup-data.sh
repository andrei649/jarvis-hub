#!/usr/bin/env bash
#
# backup-data.sh — Backup & restore Jarvis personal data (H12.15).
#
# agents/data/ + memory_logs/ are git-ignored (local-first ethos) and hold the
# ONLY real-data state: H8 personal memory, sessions/checkpoints, audit log,
# user-built workflows, and the ingested corpus. They are not in git and not on
# GitHub — so a `git clean`/reinstall wipes them permanently. This script gives
# you a local safety net.
#
# Usage:
#   scripts/backup-data.sh                 # create a backup in ./backups/
#   scripts/backup-data.sh backup [dir]    # create a backup in [dir]
#   scripts/backup-data.sh restore <file>  # restore from an archive (overwrites)
#   scripts/backup-data.sh list            # list existing backups
#
# Env: BACKUP_DIR overrides the default destination (e.g. an external/cloud drive).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIRS=(agents/data memory_logs)
DEST="${BACKUP_DIR:-$ROOT/backups}"
KEEP=14  # retain the most recent N backups

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-1}"; }

cmd="${1:-backup}"
case "$cmd" in
  backup)
    [ -n "${2:-}" ] && DEST="$2"
    present=()
    for d in "${DATA_DIRS[@]}"; do [ -e "$ROOT/$d" ] && present+=("$d"); done
    if [ "${#present[@]}" -eq 0 ]; then
      echo "Nothing to back up yet (no agents/data or memory_logs)."; exit 0
    fi
    mkdir -p "$DEST"
    ts="$(date +%Y%m%d-%H%M%S)"
    out="$DEST/jarvis-data-$ts.tar.gz"
    tar -czf "$out" -C "$ROOT" "${present[@]}"
    echo "✓ Backup created: $out ($(du -h "$out" | cut -f1))"
    # Retention: drop everything older than the most recent $KEEP.
    ls -1t "$DEST"/jarvis-data-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" | xargs -r rm -f
    ;;
  restore)
    arc="${2:-}"
    [ -f "$arc" ] || { echo "Archive not found: '${arc:-}'"; usage 1; }
    echo "About to restore '$arc' into $ROOT"
    echo "This OVERWRITES current agents/data/ and memory_logs/."
    read -r -p "Continue? [y/N] " ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Aborted."; exit 1; }
    tar -xzf "$arc" -C "$ROOT"
    echo "✓ Restored from $arc"
    ;;
  list)
    ls -1t "$DEST"/jarvis-data-*.tar.gz 2>/dev/null || echo "No backups in $DEST"
    ;;
  -h|--help|help) usage 0 ;;
  *) echo "Unknown command: $cmd"; usage 1 ;;
esac
