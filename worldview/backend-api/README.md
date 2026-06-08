# WorldView Backend API

Node.js / **Fastify** service that powers the 4D Playback Engine: REST endpoints serving
**historical state** from TimescaleDB (as-of-T reconstruction) and a **WebSocket** stream
serving **live state** from Redis (snapshot + pub/sub deltas).

## Status

STEP 4 implemented — the 4D API:

- **REST `GET /history/:layer?t=<unix>&bbox=w,s,e,n&lod=raw|minute`** — as-of-T reconstruction
  per layer (`adsb`, `ais`, `tle`, `ew`, `context`) from TimescaleDB via
  `DISTINCT ON ... WHERE ts <= T`, returned as a GeoJSON FeatureCollection (design doc §8.2).
  `lod=minute` reads 1-minute continuous-aggregate rollups for `adsb`/`ais` (zoomed-out /
  fast scrubbing, §8.3); bbox is clamped to WGS84 and queries are capped at 50k features.
- **REST `GET /history/:layer/:entityId/track?from=<unix>&to=<unix>`** — one entity's trail
  (`adsb`/`ais`/`tle`) over a window as a GeoJSON LineString with per-vertex `coordTimes`.
- **WebSocket `/live?layers=...`** — sends a Redis snapshot per layer on connect, then streams
  deltas published on `chan:<layer>`. Clients may send `{"type":"viewport","bbox":"w,s,e,n"}`
  to receive only deltas inside their viewport (per-connection; default streams everything).
- **Live-writer** (`consumers/liveWriter.ts`) — Kafka→Redis consumer that upserts the latest
  state per entity (string key + geo set + TTL) and publishes deltas. Opt-in (`ENABLE_LIVE_WRITER=1`).
- **History-writer** (`consumers/historyWriter.ts`) — Kafka→TimescaleDB consumer that batches
  envelopes per domain (~5k rows or 500ms) into the right hypertable with idempotent
  `ON CONFLICT DO NOTHING` inserts; geometry built in-DB from lon/lat/alt or `geom_wkt`.
  Opt-in (`ENABLE_HISTORY_WRITER=1`). This is what populates `/history`. On a batch error it
  falls back to per-row inserts so one poison row can't drop the whole batch.
- **`/health`** (liveness) and **`/ready`** (pings Redis + TimescaleDB).

Validated: `tsc --noEmit` clean; **13 unit tests** (`npm test`) cover the batch-insert builder
and helpers; all five history queries + the full write→read round-trip verified against real
PostGIS (latest-≤-T per entity, future rows excluded, in-DB geometry, idempotent re-writes,
context routed to dark_vessel_events / geopolitical_events); server boots and the WebSocket
upgrade succeeds.

```bash
npm test --workspace backend-api     # 13 unit tests, no infra required
```

## Develop

```bash
npm install                    # from worldview/ root (workspaces)
cp .env.example .env
npm run dev --workspace backend-api
curl 'localhost:4000/health'
curl 'localhost:4000/history/adsb?t=1749200400&bbox=55,25,58,28'
```

## Layout

```
src/server.ts          Fastify bootstrap (REST + WS + optional live-writer)
src/config.ts          env-derived config
src/types.ts           layers, BBox parsing, liveness windows + TTLs
src/geojson.ts         rows -> GeoJSON FeatureCollection
src/repositories/      history.ts (read: as-of-T) + historyWriter.ts (write: batch insert) + live.ts
src/consumers/         liveWriter.ts (Kafka -> Redis) + historyWriter.ts (Kafka -> TimescaleDB)
src/routes/            health.ts, history.ts, live.ts
src/plugins/           redis.ts (ioredis) + db.ts (pg pool)
test/                  node:test unit tests (run via tsx)
```
