# Deploying WorldView

WorldView is a streaming, time-series geospatial platform. The pieces:

| Service | Role | Scales by |
| --- | --- | --- |
| **Redpanda / Kafka** | buffers the OSINT firehose | partitions per topic (§4 of the design doc) |
| **TimescaleDB + PostGIS** | durable history (hypertables, continuous aggregates) | chunk interval, compression, read replicas |
| **Redis** | live-state cache + pub/sub | memory; cluster for very high fan-out |
| **ingestion-workers** | fetch + normalize → Kafka | one (or more) per domain; Kafka consumer-group parallelism |
| **backend-api** (Fastify) | REST `/history` + WS `/live`; the Kafka→Redis/TimescaleDB consumers | stateless — run N replicas behind a load balancer |
| **frontend** (Next.js) | the dashboard | static/CDN or N replicas |

## Local / single-host (Docker Compose)

Infra only (the dev default):

```bash
docker compose up -d            # Redpanda + TimescaleDB (schema auto-applied) + Redis
```

Full stack (infra + API + workers + dashboard):

```bash
MAPBOX_ACCESS_TOKEN=pk.xxx docker compose -f docker-compose.yml -f docker-compose.app.yml up --build
```

> The Dockerfiles (`backend-api/`, `frontend/`, `ingestion-workers/`) are templates — they are
> **not built in this repo's CI** (no Docker daemon there). Build and smoke-test them in an
> environment with Docker before relying on them in production.

## Configuration

Per-service environment (see each service's `.env.example`):

- **API** (`backend-api`): `DATABASE_URL`, `REDIS_URL`, `KAFKA_BROKERS`, `CORS_ORIGIN`,
  `ENABLE_LIVE_WRITER=1`, `ENABLE_HISTORY_WRITER=1` (the Kafka consumers; run them in at least
  one replica). Without the flags the API only serves reads.
- **Workers** (`ingestion-workers`): `KAFKA_BROKERS` + per-source credentials
  (`OPENSKY_*`, `AISSTREAM_API_KEY`, `SPACETRACK_*`). Run with `python -m worldview_ingest <domain>`.
- **Frontend**: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN`
  (inlined at build time).

## Database setup

The schema is applied automatically on first TimescaleDB boot (mounted to
`/docker-entrypoint-initdb.d`). For an external/managed Postgres, apply it manually:

```bash
for f in db/schema/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```

This requires **PostgreSQL 15+ with PostGIS 3.4+ and TimescaleDB 2.x** (the CI integration job
runs against `timescale/timescaledb-ha:pg16`, which validates the full schema, continuous
aggregates, and policies).

## Scaling notes

- **Ingestion throughput:** size Kafka partitions per topic to the peak message rate and run
  that many worker/consumer instances (ADS-B is the heaviest — 24 partitions in the design).
- **History writes:** the `history-writer` batches inserts (≈5k rows / 500 ms) and is idempotent
  on the PK, so run multiple replicas safely (at-least-once + `ON CONFLICT DO NOTHING`).
- **Reads:** the API is stateless; put N replicas behind a load balancer. Use TimescaleDB read
  replicas and the `lod=minute` continuous-aggregate path for zoomed-out / long-range queries.
- **Live fan-out:** Redis pub/sub feeds the WebSockets; for very high client counts, shard Redis
  or add a fan-out tier, and have clients send viewport bounds to cut delta volume.
