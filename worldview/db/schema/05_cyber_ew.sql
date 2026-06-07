-- WorldView :: 05_cyber_ew.sql
-- Layer D — Cyber & Electronic Warfare. Internet blackouts (IODA) + GPS jamming (H3 grid).
--
-- H3 NOTE: the h3_index is stored as text and the cell boundary is stored explicitly as a
-- polygon, so this works WITHOUT the native `h3` Postgres extension (computed app-side in the
-- ingestion worker). If you enable the h3/h3_postgis extensions in 00_extensions.sql you may
-- change h3_index to the native `h3index` type and derive the boundary in-DB.

-- ---------------------------------------------------------------------------
-- Internet outages from IODA. Low cardinality (country / ASN). Region polygon for render.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS internet_outages (
    ts            timestamptz NOT NULL,
    entity_id     text        NOT NULL,             -- 'country:IR' | 'asn:12880' (composite key)
    country       text,                             -- ISO code
    asn           integer,                          -- autonomous system number (nullable)
    score         real        NOT NULL,             -- IODA outage severity (0=normal .. 1=blackout)
    region_geom   geometry(MultiPolygon, 4326),     -- affected region for map shading
    source        text        NOT NULL DEFAULT 'ioda',
    ingested_at   timestamptz NOT NULL DEFAULT now(),  -- transaction time (provenance)
    PRIMARY KEY (entity_id, ts)
);

SELECT create_hypertable(
    'internet_outages', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- ---------------------------------------------------------------------------
-- GPS jamming aggregated into H3 hexagons (§9.3). One row per (cell, time-bucket).
-- Target resolution ~r5 (~8 km edge): fidelity vs render count balance.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gps_jamming (
    ts            timestamptz NOT NULL,             -- bucket start (e.g. floor to 5 min)
    h3_index      text        NOT NULL,             -- H3 cell id (app-computed)
    h3_resolution smallint    NOT NULL DEFAULT 5,
    h3_geom       geometry(Polygon, 4326) NOT NULL, -- hexagon boundary for Deck.gl H3 layer
    intensity     real        NOT NULL,             -- aggregated interference intensity (0..1)
    sample_count  integer     NOT NULL DEFAULT 0,   -- observations contributing to the bucket
    source        text        NOT NULL DEFAULT 'gpsjam',
    ingested_at   timestamptz NOT NULL DEFAULT now(),  -- transaction time (provenance)
    PRIMARY KEY (h3_index, ts)
);

SELECT create_hypertable(
    'gps_jamming', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);
