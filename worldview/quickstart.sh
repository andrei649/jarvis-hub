#!/usr/bin/env bash
# WorldView — casual quickstart. One command from zero to a read-serving 4D API
# with the Strait of Hormuz demo scenario loaded:
#
#     cd worldview && ./quickstart.sh
#
# What it does (and deliberately does NOT do):
#   1. docker compose up -d timescaledb redis   — no Redpanda/Kafka: without the
#      ENABLE_*_WRITER flags the API only serves reads (DEPLOY.md), and a casual
#      install is read-only. The full streaming stack stays `make infra-up`.
#   2. waits for Postgres to be ready (first boot pulls the image and applies
#      db/schema/*.sql via the initdb mount — can take a few minutes).
#   3. applies db/seed/demo.sql through psql INSIDE the container, so the host
#      needs no psql. Idempotent: the seed TRUNCATEs its own tables first.
#   4. npm-installs the backend-api workspace (first run only) and starts the
#      API in the foreground on http://127.0.0.1:4000 — Ctrl-C stops it; the
#      infra containers keep running (./quickstart.sh --down stops those).
#
# The JARVIS hub's World tab polls GET /api/worldview/{status,overview} and will
# flip to "connected" with real recon windows as soon as this is up.
#
# Flags:
#   --infra-only   steps 1–3 only (don't start the API)
#   --seed-live    also seed the Redis live-state (dashboard LIVE mode; needs the
#                  root workspace install for ioredis)
#   --down         stop the infra containers and exit
set -euo pipefail
cd "$(dirname "$0")"

INFRA_ONLY=0
SEED_LIVE=0
for arg in "$@"; do
  case "$arg" in
    --infra-only) INFRA_ONLY=1 ;;
    --seed-live)  SEED_LIVE=1 ;;
    --down)       exec docker compose down ;;
    *) echo "unknown flag: $arg (known: --infra-only --seed-live --down)" >&2; exit 2 ;;
  esac
done

for cmd in docker npm; do
  command -v "$cmd" >/dev/null || { echo "quickstart needs '$cmd' on PATH" >&2; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "quickstart needs the 'docker compose' plugin" >&2; exit 1; }

echo "[1/4] starting TimescaleDB + Redis (no Kafka — read-only profile)…"
docker compose up -d timescaledb redis

echo "[2/4] waiting for Postgres (first boot applies the schema — be patient)…"
for i in $(seq 1 60); do
  if docker compose exec -T timescaledb pg_isready -U worldview -d worldview >/dev/null 2>&1; then
    break
  fi
  [ "$i" = 60 ] && { echo "Postgres did not become ready in ~5 min; check: docker compose logs timescaledb" >&2; exit 1; }
  sleep 5
done
# pg_isready can flip green between initdb restarts on the very first boot; make
# sure the schema is genuinely in place before seeding.
for i in $(seq 1 30); do
  if docker compose exec -T timescaledb psql -U worldview -d worldview -tAc "SELECT 1 FROM pg_tables WHERE tablename='recon_windows'" 2>/dev/null | grep -q 1; then
    break
  fi
  [ "$i" = 30 ] && { echo "schema not applied (recon_windows missing); check: docker compose logs timescaledb" >&2; exit 1; }
  sleep 5
done

echo "[3/4] loading the Strait of Hormuz demo scenario…"
docker compose exec -T timescaledb psql -U worldview -d worldview -v ON_ERROR_STOP=1 -q < db/seed/demo.sql

if [ "$SEED_LIVE" = 1 ]; then
  echo "      seeding Redis live-state (LIVE mode)…"
  [ -d node_modules ] || npm install --no-audit --no-fund
  node scripts/seed-live.mjs
fi

if [ "$INFRA_ONLY" = 1 ]; then
  echo "done (infra only). Start the API later with: npm run dev --workspace backend-api"
  exit 0
fi

echo "[4/4] starting the WorldView API on http://127.0.0.1:4000 (Ctrl-C to stop)…"
[ -d backend-api/node_modules ] || npm install --workspace backend-api --no-audit --no-fund
exec npm run dev --workspace backend-api
