-- WorldView :: 04_space_tle.sql
-- Layer C — Space. TLE catalog (raw orbital elements) + materialized SGP4 ephemeris/footprints.

-- ---------------------------------------------------------------------------
-- Raw Two-Line Element sets as fetched (Celestrak / Space-Track). One row per epoch.
-- The propagator reads the latest TLE per satellite and materializes ephemeris below.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tle_catalog (
    norad_id     integer     NOT NULL REFERENCES satellites(norad_id) ON DELETE CASCADE,
    epoch        timestamptz NOT NULL,              -- TLE epoch (when the elements are valid)
    line1        text        NOT NULL,
    line2        text        NOT NULL,
    source       text        NOT NULL DEFAULT 'celestrak',
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (norad_id, epoch)
);

-- ---------------------------------------------------------------------------
-- Materialized satellite ephemeris (§9.2). One point per satellite per propagation
-- tick (e.g. 1/min) with the precomputed sensor footprint polygon valid at that ts.
-- Materializing (vs propagate-on-read) lets historical scrubbing use the same fast
-- DISTINCT ON path as flights/ships (ADR-7).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS satellite_ephemeris (
    ts            timestamptz      NOT NULL,
    norad_id      integer          NOT NULL,
    geom          geometry(PointZ, 4326) NOT NULL,  -- sub-satellite point; Z = altitude (m)
    velocity_kms  real,                             -- scalar speed (km/s), for display
    sensor_type   text             NOT NULL,        -- denormalized: optical | sar | sigint | other
    footprint     geometry(Polygon, 4326),          -- ground footprint (cone / swath / coverage)
    is_sunlit     boolean,                          -- optical sensors need daylight at target
    PRIMARY KEY (norad_id, ts)
);

SELECT create_hypertable(
    'satellite_ephemeris', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);
