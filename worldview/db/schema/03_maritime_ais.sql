-- WorldView :: 03_maritime_ais.sql
-- Layer B — Maritime (AIS) positions + Dark Vessel Detection events. 6h chunks, by mmsi.

CREATE TABLE IF NOT EXISTS ais_positions (
    ts            timestamptz      NOT NULL,
    mmsi          bigint           NOT NULL,
    geom          geometry(Point, 4326) NOT NULL,   -- vessels are sea-level: 2D point
    sog_kt        real,                             -- speed over ground (knots)
    cog_deg       real,                             -- course over ground
    heading_deg   real,                             -- true heading (may differ from COG)
    nav_status    smallint,                         -- AIS navigational status code
    source        text             NOT NULL,        -- 'terrestrial' | 'satellite' | feed name (lineage)
    ingested_at   timestamptz      NOT NULL DEFAULT now(), -- transaction time (provenance)
    PRIMARY KEY (mmsi, ts)
);

SELECT create_hypertable(
    'ais_positions', 'ts',
    partitioning_column => 'mmsi',
    number_partitions   => 4,
    chunk_time_interval => INTERVAL '6 hours',
    if_not_exists       => TRUE
);

-- ---------------------------------------------------------------------------
-- Dark Vessel events (§9.1): a vessel went silent while inside a watched geofence.
-- Emitted by the dark-vessel-detector consumer. Participates in the 4D timeline.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dark_vessel_events (
    ts                timestamptz NOT NULL,         -- time the gap was detected/flagged
    mmsi              bigint      NOT NULL,
    geofence_id       bigint      NOT NULL REFERENCES geofences(id),
    last_seen_ts      timestamptz NOT NULL,         -- last AIS report before going dark
    last_seen_geom    geometry(Point, 4326) NOT NULL,
    gap_seconds       integer     NOT NULL,         -- silence duration at flag time
    extrapolated_geom geometry(Point, 4326),        -- dead-reckoned position from last COG/SOG
    status            text NOT NULL DEFAULT 'dark'  -- dark | resumed | cleared
                        CHECK (status IN ('dark','resumed','cleared')),
    metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
    source            text  NOT NULL DEFAULT 'unknown',   -- lineage handle (detector / feed)
    ingested_at       timestamptz NOT NULL DEFAULT now(), -- transaction time (provenance)
    -- ts (detection time) must be in the PK: TimescaleDB requires the partitioning
    -- column to participate in every unique constraint on a hypertable.
    PRIMARY KEY (mmsi, ts)
);

SELECT create_hypertable(
    'dark_vessel_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);
