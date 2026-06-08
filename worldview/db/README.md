# WorldView Database Schema

TimescaleDB + PostGIS DDL for the WorldView 4D OSINT platform. See the design rationale in
[`../docs/01-architecture-and-schema.md`](../docs/01-architecture-and-schema.md).

## Prerequisites

- **PostgreSQL 15+**
- **PostGIS 3.4+**
- **TimescaleDB 2.x**
- *(optional)* the `h3` + `h3_postgis` extensions. If absent, the EW layer falls back to an
  app-computed `h3_index text` column — the schema works either way (see `05_cyber_ew.sql`).

The easiest way to get all three in one image is `timescale/timescaledb-ha:pg16` (ships with
PostGIS and the TimescaleDB toolkit).

## Apply order

The files are numbered and **must be run in order** (later files depend on extensions,
reference tables, and hypertables defined earlier):

```bash
for f in schema/*.sql; do
  psql --no-psqlrc --set ON_ERROR_STOP=on -d worldview -f "$f"
done
```

| File | Purpose |
| --- | --- |
| `00_extensions.sql` | enable PostGIS, TimescaleDB, (optional) H3 |
| `01_reference.sql` | slowly-changing dimension tables (aircraft, vessels, satellites, geofences, footprint params) |
| `02_aerospace_adsb.sql` | Layer A — ADS-B position hypertable |
| `03_maritime_ais.sql` | Layer B — AIS position hypertable + dark-vessel events |
| `04_space_tle.sql` | Layer C — TLE catalog + materialized satellite ephemeris/footprints |
| `05_cyber_ew.sql` | Layer D — IODA outages + GPS-jamming H3 cells |
| `06_context_intel.sql` | Layer E — NOTAMs, strike zones, geopolitical events |
| `07_policies.sql` | continuous aggregates + compression + retention policies |
| `08_indexes.sql` | spatial (GiST) + as-of (composite) indexes |

## Demo data

After the schema is applied, load a Strait of Hormuz scenario spanning all five layers over the
last 10 minutes (so scrubbing the timeline animates):

```bash
psql "$DATABASE_URL" -f seed/demo.sql     # or: npm run db:seed
```

## Notes

- All geometry is stored as `geometry(…, 4326)` (WGS84) and cast to `geography` only where
  geodesic distance is needed (dark-vessel gap, geofence containment).
- Fact tables use `(entity_id, ts)` primary keys so at-least-once Kafka delivery is idempotent
  (`ON CONFLICT DO NOTHING`).
- This DDL targets the documented PostGIS/TimescaleDB APIs; live validation against a running
  cluster is part of STEP 2 (infra) — STEP 1 ships the schema, not a provisioned database.
