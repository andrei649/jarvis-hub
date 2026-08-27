#!/bin/bash
# SessionStart hook: make WorldView workspace dependencies available.
#
# WorldView (worldview/) is an npm workspace covering frontend + backend-api.
# A fresh Claude Code on the web container clones the repo without node_modules,
# which breaks `vite build` with unresolved-import errors (cesium, tailwind, vitest).
# Installing here makes the frontend build / typecheck / test work out of the box.
set -euo pipefail

# Only run in Claude Code on the web (ephemeral remote containers). Local dev
# environments manage their own node_modules.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

WORKSPACE="$ROOT/worldview"
LOCKFILE="$WORKSPACE/package-lock.json"
STAMP="$WORKSPACE/node_modules/.jarvis-package-lock.sha256"

if [ ! -f "$LOCKFILE" ]; then
  echo "[session-start] Missing worldview/package-lock.json; refusing a mutable install." >&2
  exit 1
fi

# SessionStart runs again after context compaction. Key the warm path to the
# immutable lockfile so repeated starts are effectively free and never mutate
# dependency resolution merely because a new AI session began.
LOCK_HASH="$(sha256sum "$LOCKFILE" | awk '{print $1}')"
if [ -d "$WORKSPACE/node_modules" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$LOCK_HASH" ]; then
  echo "[session-start] WorldView dependencies already match package-lock.json." >&2
  exit 0
fi

# All progress output goes to stderr: SessionStart stdout is injected into the
# model's context, so npm chatter must not consume the context budget.
echo "[session-start] Restoring WorldView dependencies from package-lock.json..." >&2
( cd "$WORKSPACE" && npm ci --no-audit --no-fund --loglevel=error ) >&2
mkdir -p "$WORKSPACE/node_modules"
printf '%s\n' "$LOCK_HASH" > "$STAMP"
echo "[session-start] WorldView dependencies ready." >&2
