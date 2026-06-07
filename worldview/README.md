# WorldView

> A 4D OSINT command center — fuse live and historical air / sea / space / cyber signals onto a unified, time-scrubbable 3D globe.

WorldView is a high-throughput, time-series geospatial platform inspired by Bilawal Sidhu's
"God's Eye View." It ingests the global firehose of open-source intelligence (ADS-B flights,
AIS vessels, satellite ephemeris, GPS-jamming and internet-blackout telemetry, NOTAMs and
geopolitical events), normalizes it through a streaming pipeline, and serves any moment in
time — live or historical — to a Deck.gl-rendered globe.

## Why it lives here

WorldView is a **separate stack** from the Python JARVIS platform that powers the rest of this
repo. It is fully self-contained under `worldview/` and shares no runtime with `agents/`.

## Tech stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 14 (App Router), TypeScript, TailwindCSS |
| Geospatial render | Deck.gl + Mapbox GL JS (millions of points @ 60fps) |
| Client state | Zustand (the global "System Master Time" timeline) |
| API | Node.js / Fastify, REST + WebSockets |
| Stream broker | Apache Kafka (or Redpanda) |
| History store | PostgreSQL + PostGIS + TimescaleDB hypertables |
| Live-state cache | Redis |
| Ingestion | Python / Node workers (SGP4, H3, AIS/ADS-B parsers) |

## Data layers

- **A — Aerospace (ADS-B):** commercial + military flight tracking.
- **B — Maritime (AIS):** vessel tracking with **Dark Vessel Detection** in geofenced choke points (e.g. Strait of Hormuz).
- **C — Space (TLE / SGP4):** live propagation of optical + SAR satellites (Maxar, Capella, Topaz) and their sensor footprints.
- **D — Cyber & EW:** internet-blackout monitoring (IODA) and GPS-jamming mapped onto Uber H3 hex grids.
- **E — Contextual Intel:** airspace closures (NOTAMs), strike zones, active geopolitical events.

## Build roadmap

The platform is built in five sequential, gated steps:

1. **Architecture & Schema** ✅ — design doc + TimescaleDB/PostGIS SQL + Kafka pipeline design.
2. **Project Scaffold** ✅ — monorepo skeleton (`frontend`, `backend-api`, `ingestion-workers`) + local infra (`docker-compose.yml`).
3. **Data Ingestion Workers** ✅ — TLE/SGP4, H3 jamming grids, AIS/ADS-B normalizers, dark-vessel detector.
4. **The 4D API** ✅ — Fastify REST `/history` + WebSocket `/live` serving live (Redis) and historical (TimescaleDB) state.
5. **Frontend Geospatial UI** ✅ — Next.js dashboard, Deck.gl map, timeline scrubber, Zustand sync.

All five steps are implemented end to end.

## Capabilities

| Area | What's implemented |
| --- | --- |
| **4D playback** | One Zustand master clock drives every layer; seamless live (WebSocket deltas) ↔ historical (`DISTINCT ON` as-of-T) toggle; play/pause, speed, 24h scrub. |
| **Ingestion** | ADS-B (OpenSky) + AIS (AISStream) normalizers; TLE→SGP4 propagation (TEME→WGS84) with optical/SAR/coverage footprints; EW→H3 aggregation; NOTAM/event parser; dark-vessel detector. |
| **Data path** | Kafka → **live-writer** (Redis) + **history-writer** (TimescaleDB, batched, idempotent, per-row poison isolation). |
| **API** | REST `/history/:layer` (as-of-T, bbox-clamped, 50k cap, `lod=minute` rollups) + `/history/:layer/:id/track` (trails) + WebSocket `/live` (snapshot + deltas) + `/health`/`/ready`. |
| **UI** | Deck.gl globe over Mapbox; timeline scrubber; layer toggles; **entity trails** (click to trace); per-entity **hover tooltips**; **stats HUD** with **dark-vessel alerts**; zoom-driven **level-of-detail**. |
| **Domain depth** | Dark Vessel Detection (geofenced AIS-gap + dead-reckoning); satellite **daylight/recon windows** (`is_sunlit`); military flight tagging; H3 jamming intensity. |
| **Quality** | Tests across all three services (Python pytest, Node `node:test`, frontend vitest); path-filtered CI (ruff + pytest + tsc + build); schemas validated against real PostGIS. |

## Contents

- [`docs/01-architecture-and-schema.md`](docs/01-architecture-and-schema.md) — the architecture & schema design document.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — evaluation vs God's Eye View + Palantir, feature picks, and the phased roadmap (standalone + JARVIS).
- [`DEPLOY.md`](DEPLOY.md) — production deployment & scaling.
- [`db/schema/`](db/schema/) — TimescaleDB + PostGIS DDL · [`db/seed/demo.sql`](db/seed/demo.sql) — the demo scenario.
- [`db/README.md`](db/README.md) — how to apply the schema and seed.
- [`docker-compose.yml`](docker-compose.yml) — local infra (Redpanda, TimescaleDB, Redis).
- [`frontend/`](frontend/) — Next.js 14 + Deck.gl dashboard.
- [`backend-api/`](backend-api/) — Fastify REST + WebSocket 4D API.
- [`ingestion-workers/`](ingestion-workers/) — Python OSINT ingestion workers.
- [`shared/schemas/`](shared/schemas/) — the canonical telemetry envelope JSON Schema.

## Quick start (local dev)

```bash
cd worldview
cp .env.example .env
docker compose up -d                  # Redpanda + TimescaleDB (schema auto-applied) + Redis
npm install                           # frontend + backend-api workspaces
npm run dev:api                       # http://localhost:4000/health
npm run dev:frontend                  # http://localhost:3000
```

### See it with data (no live feeds needed)

```bash
export DATABASE_URL=postgres://worldview:worldview@localhost:5432/worldview
npm run db:seed     # loads a Strait of Hormuz scenario across all 5 layers, last 10 min
```

Then open the dashboard and **scrub the timeline back ~10 minutes** (historical mode): a civil
flight crossing the strait, a military orbit, a transiting tanker, a vessel going **dark**, a
SAR satellite pass with footprint, a ramping **GPS-jamming** cell, a NOTAM, and a strike event —
all moving in lockstep with the master clock.

For **LIVE mode** without running Kafka/workers, seed Redis directly:

```bash
export REDIS_URL=redis://localhost:6379
npm run seed:live   # writes a live snapshot the /live WebSocket serves immediately
```

(For the real pipeline, run the ingestion workers with the API's `ENABLE_LIVE_WRITER=1` /
`ENABLE_HISTORY_WRITER=1`.)
