# WorldView Backend API

Node.js / **Fastify** service that powers the 4D Playback Engine: REST endpoints serving
**historical state** from TimescaleDB (as-of-T reconstruction) and a **WebSocket** stream
serving **live state** from Redis (snapshot + pub/sub deltas).

## Status

STEP 4 implemented — the 4D API:

- **REST `GET /history/:layer?t=<unix>&bbox=w,s,e,n`** — as-of-T reconstruction per layer
  (`adsb`, `ais`, `tle`, `ew`, `context`) from TimescaleDB via `DISTINCT ON ... WHERE ts <= T`,
  returned as a GeoJSON FeatureCollection (design doc §8.2).
- **WebSocket `/live?layers=...`** — sends a Redis snapshot per layer on connect, then streams
  deltas published on `chan:<layer>`.
- **Live-writer** (`consumers/liveWriter.ts`) — Kafka→Redis consumer that upserts the latest
  state per entity (string key + geo set + TTL) and publishes deltas. Opt-in (`ENABLE_LIVE_WRITER=1`).
- **`/health`** (liveness) and **`/ready`** (pings Redis + TimescaleDB).

Validated: `tsc --noEmit` clean; all five history queries verified against real PostGIS
(latest-≤-T per entity, future rows excluded, bbox filtering, footprints, NOTAM interval
containment, dark-vessel temporal gating); server boots and the WebSocket upgrade succeeds.

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
src/repositories/      history.ts (TimescaleDB as-of-T) + live.ts (Redis snapshot)
src/consumers/         liveWriter.ts (Kafka -> Redis + pub/sub)
src/routes/            health.ts, history.ts, live.ts
src/plugins/           redis.ts (ioredis) + db.ts (pg pool)
```
