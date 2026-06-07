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
-- ===========================================================================

SELECT add_retention_policy('adsb_positions',      INTERVAL '90 days',  if_not_exists => TRUE);
SELECT add_retention_policy('ais_positions',       INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('satellite_ephemeris', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('gps_jamming',         INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('internet_outages',    INTERVAL '365 days', if_not_exists => TRUE);
-- dark_vessel_events + geopolitical_events are intelligence records: no auto-retention.
