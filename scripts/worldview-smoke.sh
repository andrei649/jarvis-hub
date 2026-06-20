#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/signal-layer"
npm test
