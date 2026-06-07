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
4. **The 4D API** ✅ *(current)* — Fastify REST `/history` + WebSocket `/live` serving live (Redis) and historical (TimescaleDB) state.
5. **Frontend Geospatial UI** — Next.js dashboard, Deck.gl map, timeline scrubber, Zustand sync.

## Contents

- [`docs/01-architecture-and-schema.md`](docs/01-architecture-and-schema.md) — the STEP 1 design document.
- [`db/schema/`](db/schema/) — TimescaleDB + PostGIS DDL.
- [`db/README.md`](db/README.md) — how to apply the schema.
- [`docker-compose.yml`](docker-compose.yml) — local infra (Redpanda, TimescaleDB, Redis).
- [`frontend/`](frontend/) — Next.js 14 + Deck.gl dashboard (scaffold).
- [`backend-api/`](backend-api/) — Fastify REST + WebSocket 4D API (scaffold).
- [`ingestion-workers/`](ingestion-workers/) — Python OSINT normalizers (scaffold).
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
