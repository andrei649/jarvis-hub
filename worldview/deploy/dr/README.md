# WorldView — disaster recovery (ticket H19.5.6)

DR-side mechanics for the WorldView platform: a **TimescaleDB streaming replica**
of the primary and **Redpanda topic mirroring** of the `osint.*` firehose to a DR
cluster, plus a **rehearsable game-day drill** that measures RPO/RTO proxies and
prints PASS/FAIL.

> **Scope note (read this).** This delivers the DR *mechanics* + a drill you can
> run on one machine. **True multi-AZ resilience and the real RPO/RTO numbers
> require a real multi-zone deployment** (primary and DR in different
> availability zones, independent power/network/storage). Locally everything
> shares one host, so the measured lag/promotion times prove the **mechanism**,
> not production SLOs. The per-zone wiring (separate VPC subnets, cross-AZ
> security groups, real `pg_hba` source ranges) is the production follow-up.

## Topology

```
        AZ-a (primary)                              AZ-b (DR)
   ┌────────────────────┐                    ┌────────────────────┐
   │ timescaledb        │  WAL streaming     │ timescaledb-dr     │
   │  (primary, :5432)  │ ─────────────────► │  (hot standby,     │
   │  slot=dr_slot      │   physical repl    │   :5433, read-only)│
   └────────────────────┘                    └────────────────────┘
   ┌────────────────────┐                    ┌────────────────────┐
   │ redpanda (:9092)   │  rpk topic mirror  │ redpanda-dr (:9093)│
   │  osint.*           │ ─────────────────► │  osint.* (mirrored)│
   └────────────────────┘                    └────────────────────┘
```

On disaster: **promote** `timescaledb-dr` (it becomes a writable primary), point
the app at it (`:5433` locally / the DR endpoint in prod) and at `redpanda-dr`,
and ingestion/serving continues from the mirrored topics.

## Components (all images pinned)

| Service | Image | Role |
| --- | --- | --- |
| `timescaledb-dr` | `timescale/timescaledb-ha:pg16` | streaming hot-standby replica of the primary (bootstraps via `pg_basebackup -R`) |
| `redpanda-dr` | `redpandadata/redpanda:v24.2.7` | DR Kafka cluster (mirror target) |
| `redpanda-mirror-init` | `redpandadata/redpanda:v24.2.7` | one-shot: ensures `osint.*` exist on DR + sets up mirroring |

The DR image **must match the primary** (`timescaledb-ha:pg16`) — physical
streaming replication requires identical major version + extensions.

## Primary-side prerequisites (TODOs — apply to the real `timescaledb`)

Streaming replication needs the **primary** configured. These are **not** set by
this compose (it only stands up the DR side); the parent applies them to the
real primary. Until they exist, `timescaledb-dr`'s `pg_basebackup` logs the
exact missing item and the game-day RPO check FAILs with "no replication
connection".

1. **`postgresql.conf`** (most are defaults on `timescaledb-ha:pg16`, listed for completeness):
   ```
   wal_level = replica           # default; logical also works
   max_wal_senders = 10          # >= number of standbys + base backups
   wal_keep_size = '512MB'       # backstop if the slot is dropped
   hot_standby = on              # (set on the standby; harmless on primary)
   ```
2. **Physical replication slot** (so the primary retains WAL for the standby):
   ```sql
   SELECT pg_create_physical_replication_slot('dr_slot');
   ```
   (The DR `pg_basebackup` uses `-S dr_slot -C` to create-if-absent, but
   pre-creating it guarantees WAL retention from the start.)
3. **Replication role** matching `REPL_USER`/`REPL_PASSWORD` in the compose:
   ```sql
   CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';
   ```
4. **`pg_hba.conf`** — allow the replication connection from the DR subnet:
   ```
   host  replication  replicator  <dr-subnet-or-container-net>/24  scram-sha-256
   ```
   Locally the DR container is on `worldview_default`; in prod use the AZ-b CIDR.
5. **`primary_conninfo`** on the standby is written automatically by
   `pg_basebackup -R` (host/port/user/slot from the compose env). No manual step.

## Run

```bash
cd worldview
docker compose up -d                                   # primary infra first
docker compose -f docker-compose.yml \
  -f deploy/dr/docker-compose.dr.yml up -d             # DR replica + mirror

docker compose -f docker-compose.yml -f deploy/dr/docker-compose.dr.yml ps
docker logs -f worldview-timescaledb-dr                # watch base-backup + stream
```

- DR Postgres (read-only standby): `localhost:5433`
- DR Redpanda (mirror target): `localhost:9093`
- Verify the standby is streaming, from the primary:
  ```bash
  docker exec -it worldview-timescaledb \
    psql -U worldview -d worldview -c "SELECT client_addr, state, replay_lag FROM pg_stat_replication;"
  ```

## Run the game-day drill

```bash
# safe: checks replication lag (RPO) + mirrored topics, NO promotion
deploy/dr/game-day.sh

# full: also promotes the DR replica + measures promotion time (RTO).
# DESTRUCTIVE to the standby — it stops being a replica.
deploy/dr/game-day.sh --promote
```

What it checks (and the targets):

| Step | Check | Proxy for |
| --- | --- | --- |
| preflight | primary + DR containers running | drill can proceed |
| replica state | DR node `pg_is_in_recovery() = t` | standby is live |
| **RPO** | `pg_stat_replication` lag seconds **≤ 5 min** | data-loss window |
| **mirror** | every `osint.*` topic present on `redpanda-dr` | stream continuity |
| **RTO** | `pg_promote()` wall-time **≤ 30 min** (then write probe) | failover time |

It is `set -euo pipefail`, guarded (missing containers → clean FAIL, not a
crash), idempotent, and never promotes without `--promote`. Exit 0 = PASS, 1 =
FAIL. Targets are overridable via `RPO_TARGET_S` / `RTO_TARGET_S` env vars.

## Kafka mirroring detail

`redpanda-mirror-init` first ensures the `osint.*` topics exist on the DR broker,
then attempts Redpanda's native multi-cluster mirroring via
`rpk cluster mirror create` (producer-side, no extra JVM). If the bundled `rpk`
build lacks that verb (it is partly enterprise-gated), the init container logs a
**MirrorMaker2** fallback. MM2 template (`mm2.properties`), run with
`connect-mirror-maker mm2.properties` from a Kafka distro:

```properties
clusters = primary, dr
primary.bootstrap.servers = redpanda:29092
dr.bootstrap.servers      = redpanda-dr:29093
primary->dr.enabled       = true
primary->dr.topics        = osint\..*
replication.factor        = 1
tasks.max                 = 2
# keep DR topic names identical to the source (no "primary." prefix):
replication.policy.class  = org.apache.kafka.connect.mirror.IdentityReplicationPolicy
```

Either way the DR cluster ends up with the same `osint.adsb / ais / tle / ew /
context / recon` topics, which the game-day `mirror` step verifies.

## Failover runbook (summary)

1. Confirm the primary is truly down (avoid split-brain).
2. `deploy/dr/game-day.sh --promote` (or `SELECT pg_promote();` on the standby).
3. Repoint the app: DB → DR endpoint (`:5433` local), Kafka → `redpanda-dr`
   (`:9093` local).
4. Stand up a **new** standby from the promoted node (it is now the primary):
   repeat the prerequisites with roles reversed. Do **not** restart the old
   primary against the new one without re-basebackup/`pg_rewind` (split-brain).

## Image pins

| Image | Tag |
| --- | --- |
| timescale/timescaledb-ha | pg16 |
| redpandadata/redpanda | v24.2.7 |
