-- WorldView :: 07_policies.sql
-- Continuous aggregates (downsampling for zoomed-out / long-range scrubbing, §8.3) +
-- compression + retention policies (the hot -> warm -> cold lifecycle, §10).
-- Continuous aggregates must be created in their own transaction; run this file standalone.

-- ===========================================================================
-- CONTINUOUS AGGREGATES — pre-rolled position buckets so the 4D engine can read
-- summaries instead of raw points when zoomed out or scrubbing fast.
-- ===========================================================================

-- 1-minute ADS-B rollup: last-known position per aircraft per minute.
CREATE MATERIALIZED VIEW IF NOT EXISTS adsb_positions_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', ts) AS bucket,
    icao24,
    last(geom, ts)  AS geom,
    last(alt_m, ts) AS alt_m,
    last(gs_kt, ts) AS gs_kt,
    last(track_deg, ts) AS track_deg,
    bool_or(is_military) AS is_military
FROM adsb_positions
GROUP BY bucket, icao24
WITH NO DATA;

-- 1-minute AIS rollup: last-known position per vessel per minute.
CREATE MATERIALIZED VIEW IF NOT EXISTS ais_positions_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', ts) AS bucket,
    mmsi,
    last(geom, ts)   AS geom,
    last(sog_kt, ts) AS sog_kt,
    last(cog_deg, ts) AS cog_deg
FROM ais_positions
GROUP BY bucket, mmsi
WITH NO DATA;

-- Spatial index on each continuous aggregate's geom. The minute-LOD bbox reads
-- (history.ts flightsAsOf/vesselsAsOf, `geom && ST_MakeEnvelope(...)`) hit the cagg, NOT the
-- base hypertable, so they do NOT inherit the base GiST (08_indexes.sql) and would seq-scan the
-- materialized cagg. TimescaleDB 2.x supports creating an index directly on the cagg by name
-- (it is materialized into an underlying hypertable); `CREATE INDEX ... ON <cagg> USING gist`
-- applies cleanly. Guarded with IF NOT EXISTS so a re-apply is idempotent.
-- NOTE: requires a real TimescaleDB to validate (no local timescaledb here) — the CI integration
-- job's schema apply is what proves this statement is accepted by the engine.
CREATE INDEX IF NOT EXISTS adsb_positions_1m_geom_gist ON adsb_positions_1m USING gist (geom);
CREATE INDEX IF NOT EXISTS ais_positions_1m_geom_gist  ON ais_positions_1m  USING gist (geom);

-- Keep continuous aggregates current (refresh recent window on a schedule).
SELECT add_continuous_aggregate_policy('adsb_positions_1m',
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE);

SELECT add_continuous_aggregate_policy('ais_positions_1m',
    start_offset      => INTERVAL '12 hours',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE);

-- ===========================================================================
-- COMPRESSION — columnar-compress warm chunks (~10-20x smaller, still queryable).
-- segmentby = entity (groups a track's rows); orderby = ts for range efficiency.
-- ===========================================================================

ALTER TABLE adsb_positions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'icao24',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('adsb_positions', INTERVAL '2 days', if_not_exists => TRUE);

ALTER TABLE ais_positions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'mmsi',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('ais_positions', INTERVAL '2 days', if_not_exists => TRUE);

ALTER TABLE satellite_ephemeris SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'norad_id',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('satellite_ephemeris', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE gps_jamming SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'h3_index',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('gps_jamming', INTERVAL '7 days', if_not_exists => TRUE);

-- ===========================================================================
-- RETENTION — drop raw chunks past their useful window. Continuous aggregates
-- survive (separate hypertables), so long-range zoomed-out scrubbing still works.
--
-- RECONSTRUCTION INTERACTION (review CRITICAL). The default `raw`-LOD as-of-T readers (backend-api
-- history.ts) query ONLY the raw hypertable, so a reconstruction frame whose T is older than a
-- layer's horizon below would return EMPTY once its raw chunks are dropped. To avoid that silent
-- gap, reconstruction.ts (buildFrames / lodForFrame, RETENTION_HORIZON_SECONDS) routes as-of-T reads
-- OLDER than the per-layer horizon to the minute continuous aggregate (which survives retention).
-- The horizon constants there MUST stay in sync with the windows below (currently adsb 90d, ais
-- 180d — the layers that have a minute cagg).
-- ===========================================================================

SELECT add_retention_policy('adsb_positions',      INTERVAL '90 days',  if_not_exists => TRUE);
SELECT add_retention_policy('ais_positions',       INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('satellite_ephemeris', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('gps_jamming',         INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('internet_outages',    INTERVAL '365 days', if_not_exists => TRUE);
-- dark_vessel_events + geopolitical_events are intelligence records: no auto-retention.
