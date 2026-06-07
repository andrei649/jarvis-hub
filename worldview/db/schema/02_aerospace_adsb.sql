-- WorldView :: 02_aerospace_adsb.sql
-- Layer A — Aerospace (ADS-B). Highest-velocity stream. 1h chunks, space-partitioned by icao24.

CREATE TABLE IF NOT EXISTS adsb_positions (
    ts            timestamptz      NOT NULL,        -- event time (the 4th dimension)
    icao24        text             NOT NULL,        -- FK-ish to aircraft.icao24 (not enforced: facts may precede dim)
    geom          geometry(PointZ, 4326) NOT NULL,  -- lon/lat with altitude in Z (meters)
    alt_m         real,                             -- barometric/geometric altitude (meters)
    gs_kt         real,                             -- ground speed (knots)
    track_deg     real,                             -- true track over ground
    vert_rate_fpm real,                             -- vertical rate (feet/min)
    callsign      text,
    squawk        text,                             -- transponder code (e.g. '7700' emergency)
    on_ground     boolean NOT NULL DEFAULT false,
    is_military   boolean NOT NULL DEFAULT false,   -- denormalized for fast military-only filters
    source        text    NOT NULL,                 -- provenance for dedup / trust (source lineage)
    ingested_at   timestamptz NOT NULL DEFAULT now(), -- transaction time: when WorldView recorded it
    -- Idempotent ingest: at-least-once Kafka delivery dedups on (icao24, ts).
    PRIMARY KEY (icao24, ts)
);

-- Hypertable on ts; space-partition by icao24 so parallel writers/readers shard by aircraft.
SELECT create_hypertable(
    'adsb_positions', 'ts',
    partitioning_column => 'icao24',
    number_partitions   => 4,
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists       => TRUE
);
