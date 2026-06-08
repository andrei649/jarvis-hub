#!/usr/bin/env bash
# WorldView DR game-day drill — ticket H19.5.6.
# ---------------------------------------------------------------------------
# Exercises the DR mechanics against the LOCAL replica + mirror brought up by
# deploy/dr/docker-compose.dr.yml and prints PASS/FAIL vs the targets:
#
#     RPO target  <= 5 min   (proxied by replication lag at drill time)
#     RTO target  <= 30 min  (proxied by measured replica-promotion time)
#
# It is read-only by default. Promotion is DESTRUCTIVE to the standby (it stops
# being a replica), so it ONLY runs with the explicit --promote flag.
#
# Usage:
#   deploy/dr/game-day.sh             # checks lag + mirror, NO promotion (safe)
#   deploy/dr/game-day.sh --promote   # also promotes the DR replica + times RTO
#
# Env overrides (defaults match docker-compose.dr.yml):
#   PRIMARY_CONTAINER  (worldview-timescaledb)
#   DR_CONTAINER       (worldview-timescaledb-dr)
#   DR_BROKER_CONT     (worldview-redpanda-dr)
#   PGUSER PGDATABASE  (worldview / worldview)
#   RPO_TARGET_S       (300)   RTO_TARGET_S (1800)
#
# Requires: docker. bash -n clean; set -euo pipefail; guarded throughout.
set -euo pipefail

PRIMARY_CONTAINER="${PRIMARY_CONTAINER:-worldview-timescaledb}"
DR_CONTAINER="${DR_CONTAINER:-worldview-timescaledb-dr}"
DR_BROKER_CONT="${DR_BROKER_CONT:-worldview-redpanda-dr}"
PRIMARY_BROKER_CONT="${PRIMARY_BROKER_CONT:-worldview-redpanda}"
PGUSER="${PGUSER:-worldview}"
PGDATABASE="${PGDATABASE:-worldview}"
RPO_TARGET_S="${RPO_TARGET_S:-300}"
RTO_TARGET_S="${RTO_TARGET_S:-1800}"
DR_TOPICS="${DR_TOPICS:-osint.adsb osint.ais osint.tle osint.ew osint.context osint.recon}"

PROMOTE=0
[ "${1:-}" = "--promote" ] && PROMOTE=1

PASS=1
note() { printf '  %s\n' "$*"; }
fail() { printf '  [FAIL] %s\n' "$*"; PASS=0; }
ok()   { printf '  [ok]   %s\n' "$*"; }

# Run psql inside a container; returns trimmed single value. Guarded so a missing
# container is a clean FAIL, not a stack trace.
psql_in() { # <container> <sql>
  docker exec -i "$1" psql -U "$PGUSER" -d "$PGDATABASE" -tAc "$2" 2>/dev/null | tr -d '[:space:]'
}
have_container() { docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true; }

echo "=== WorldView DR game-day  ($(date -u +%FT%TZ)) ==="
echo "    RPO target <= ${RPO_TARGET_S}s | RTO target <= ${RTO_TARGET_S}s"

# ---------------------------------------------------------------------------
# 0. Preflight — containers up?
# ---------------------------------------------------------------------------
echo "--- preflight"
for c in "$PRIMARY_CONTAINER" "$DR_CONTAINER"; do
  if have_container "$c"; then ok "container up: $c"; else fail "container not running: $c"; fi
done
if [ "$PASS" -ne 1 ]; then
  echo "=== preflight FAILED — bring the stack up first:"
  echo "    docker compose -f docker-compose.yml -f deploy/dr/docker-compose.dr.yml up -d"
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. Replica sanity — is the DR node actually a standby in recovery?
# ---------------------------------------------------------------------------
echo "--- replica state"
IN_RECOVERY="$(psql_in "$DR_CONTAINER" 'SELECT pg_is_in_recovery();' || true)"
if [ "$IN_RECOVERY" = "t" ]; then
  ok "DR node is a hot standby (pg_is_in_recovery = t)"
elif [ "$IN_RECOVERY" = "f" ]; then
  note "DR node is NOT in recovery — already promoted (standalone primary)."
else
  fail "could not query DR recovery state"
fi

# ---------------------------------------------------------------------------
# 2. RPO proxy — replication lag (seconds behind primary + byte backlog).
#    Measured from the PRIMARY's pg_stat_replication (authoritative).
# ---------------------------------------------------------------------------
echo "--- RPO check (replication lag)"
LAG_S="$(psql_in "$PRIMARY_CONTAINER" \
  "SELECT COALESCE(EXTRACT(EPOCH FROM (now() - reply_time))::int, 0)
     FROM pg_stat_replication ORDER BY reply_time DESC LIMIT 1;" || true)"
REPL_COUNT="$(psql_in "$PRIMARY_CONTAINER" 'SELECT count(*) FROM pg_stat_replication;' || echo 0)"

if [ "${REPL_COUNT:-0}" = "0" ]; then
  if [ "$IN_RECOVERY" = "f" ]; then
    note "no live replication connection (DR already promoted) — skipping RPO gate."
  else
    fail "primary has NO replication connection — replica not streaming."
  fi
else
  note "active replication connections: ${REPL_COUNT}"
  LAG_S="${LAG_S:-0}"; [ -z "$LAG_S" ] && LAG_S=0
  if [ "$LAG_S" -le "$RPO_TARGET_S" ]; then
    ok "replication lag ${LAG_S}s <= RPO target ${RPO_TARGET_S}s"
  else
    fail "replication lag ${LAG_S}s > RPO target ${RPO_TARGET_S}s"
  fi
fi

# ---------------------------------------------------------------------------
# 3. Mirror verify — are the osint.* topics present on the DR broker?
# ---------------------------------------------------------------------------
echo "--- mirror check (DR broker topics)"
if have_container "$DR_BROKER_CONT"; then
  DR_TOPIC_LIST="$(docker exec -i "$DR_BROKER_CONT" \
    rpk topic list --brokers redpanda-dr:29093 2>/dev/null || true)"
  for t in $DR_TOPICS; do
    if printf '%s\n' "$DR_TOPIC_LIST" | grep -qw "$t"; then
      ok "DR topic present: $t"
    else
      fail "DR topic MISSING: $t"
    fi
  done
else
  note "DR broker container ${DR_BROKER_CONT} not running — skipping mirror check."
fi

# ---------------------------------------------------------------------------
# 4. RTO proxy — promote the DR replica + time it.  DESTRUCTIVE: --promote only.
# ---------------------------------------------------------------------------
echo "--- RTO check (replica promotion)"
if [ "$PROMOTE" -ne 1 ]; then
  note "promotion skipped (no --promote flag). Re-run with --promote to measure RTO."
  note "  deploy/dr/game-day.sh --promote"
elif [ "$IN_RECOVERY" != "t" ]; then
  note "DR node is not in recovery — nothing to promote (already a primary)."
else
  echo "  PROMOTING DR replica (pg_promote) ..."
  START_NS="$(date +%s%N)"
  if ! psql_in "$DR_CONTAINER" 'SELECT pg_promote(wait => true, wait_seconds => 60);' >/dev/null 2>&1; then
    # Fallback to pg_ctl if pg_promote() is unavailable for any reason.
    docker exec -i "$DR_CONTAINER" pg_ctl promote -D "${PGDATA:-/home/postgres/pgdata/data}" \
      >/dev/null 2>&1 || true
  fi
  # Poll until the node leaves recovery (becomes a writable primary).
  PROMOTED=0
  for _ in $(seq 1 60); do
    if [ "$(psql_in "$DR_CONTAINER" 'SELECT pg_is_in_recovery();' || echo t)" = "f" ]; then
      PROMOTED=1; break
    fi
    sleep 1
  done
  END_NS="$(date +%s%N)"
  RTO_S=$(( (END_NS - START_NS) / 1000000000 ))
  if [ "$PROMOTED" -eq 1 ]; then
    if [ "$RTO_S" -le "$RTO_TARGET_S" ]; then
      ok "promotion completed in ${RTO_S}s <= RTO target ${RTO_TARGET_S}s"
    else
      fail "promotion took ${RTO_S}s > RTO target ${RTO_TARGET_S}s"
    fi
    # Confirm the freshly-promoted node accepts a write.
    if psql_in "$DR_CONTAINER" \
        'CREATE TABLE IF NOT EXISTS dr_gameday_probe(t timestamptz); INSERT INTO dr_gameday_probe VALUES (now()); SELECT 1;' \
        >/dev/null 2>&1; then
      ok "promoted DR node accepts writes"
    else
      fail "promoted DR node did NOT accept a write"
    fi
  else
    fail "DR node did not leave recovery within timeout"
  fi
fi

# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
echo "==========================================================="
if [ "$PASS" -eq 1 ]; then
  echo "RESULT: PASS  (RPO<=${RPO_TARGET_S}s, RTO<=${RTO_TARGET_S}s targets met for the checks run)"
  exit 0
else
  echo "RESULT: FAIL  (one or more checks above failed)"
  exit 1
fi
