#!/bin/bash
# SessionStart hook: install WorldView workspace dependencies.
#
# WorldView (worldview/) is an npm workspace covering frontend + backend-api.
# A fresh Claude Code on the web container clones the repo without node_modules,
# which breaks `next build` with errors like:
#   Module not found: Can't resolve 'react-map-gl/mapbox'
# Installing here makes the frontend build / lint / test work out of the box.
set -euo pipefail

# Only run in Claude Code on the web (ephemeral remote containers). Local dev
# environments manage their own node_modules.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

echo "[session-start] Installing WorldView workspace dependencies (worldview/)..."
# `npm install` (not `ci`) is idempotent and lets the cached container reuse the
# existing tree on later runs.
( cd "$ROOT/worldview" && npm install --no-audit --no-fund )
echo "[session-start] WorldView dependencies ready."
