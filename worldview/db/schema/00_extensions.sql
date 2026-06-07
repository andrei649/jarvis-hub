-- WorldView :: 00_extensions.sql
-- Enable the spatial + time-series + (optional) hex-grid extensions.
-- Run first. Idempotent (IF NOT EXISTS).

-- Spatial geometry/geography types, GiST indexing, spatial functions.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Hypertables, continuous aggregates, compression + retention policies.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Uber H3 hexagonal grid (Layer D). OPTIONAL: not present on every install.
-- If these fail in your environment, comment them out — 05_cyber_ew.sql stores the
-- H3 index as text and the polygon explicitly, so the EW layer works without them.
-- CREATE EXTENSION IF NOT EXISTS h3;
-- CREATE EXTENSION IF NOT EXISTS h3_postgis CASCADE;

-- Sanity check: surface versions so an operator can confirm the toolchain.
DO $$
BEGIN
    RAISE NOTICE 'PostGIS:     %', postgis_full_version();
    RAISE NOTICE 'TimescaleDB: %', (SELECT extversion FROM pg_extension WHERE extname = 'timescaledb');
END
$$;
