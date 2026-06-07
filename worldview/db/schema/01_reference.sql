-- WorldView :: 01_reference.sql
-- Slowly-changing dimension / catalog tables. These are NOT hypertables; they are
-- joined to the high-velocity fact streams by entity_id. Kept small and indexed on PK.

-- ---------------------------------------------------------------------------
-- Aircraft catalog (Layer A). Keyed by the 24-bit ICAO transponder address (hex).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aircraft (
    icao24        text PRIMARY KEY,                 -- e.g. '4ca7b3'
    registration  text,                             -- tail number, e.g. 'A6-EOA'
    type_code     text,                             -- ICAO type, e.g. 'A388'
    operator      text,                             -- airline / owner
    is_military   boolean NOT NULL DEFAULT false,
    metadata      jsonb   NOT NULL DEFAULT '{}'::jsonb,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Vessel catalog (Layer B). Keyed by MMSI; IMO is the durable hull identifier.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vessels (
    mmsi          bigint PRIMARY KEY,               -- 9-digit Maritime Mobile Service Identity
    imo           bigint,                           -- durable IMO number (survives reflagging)
    name          text,
    vessel_type   text,                             -- e.g. 'tanker', 'cargo'
    flag          text,                             -- ISO country of registry
    length_m      real,
    width_m       real,
    metadata      jsonb   NOT NULL DEFAULT '{}'::jsonb,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Satellite catalog (Layer C). Keyed by NORAD ID. Sensor type drives footprint geometry.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS satellites (
    norad_id      integer PRIMARY KEY,
    name          text NOT NULL,                    -- e.g. 'WORLDVIEW-3', 'CAPELLA-10'
    operator      text,                             -- e.g. 'Maxar', 'Capella', 'NRO'
    sensor_type   text NOT NULL DEFAULT 'optical'   -- optical | sar | sigint | other
                    CHECK (sensor_type IN ('optical','sar','sigint','other')),
    is_classified boolean NOT NULL DEFAULT false,   -- e.g. USA-234 'Topaz'
    metadata      jsonb   NOT NULL DEFAULT '{}'::jsonb,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Sensor footprint parameters (Layer C, §9.2). One row per satellite; drives the
-- data-driven footprint polygon generator (cone vs swath vs coverage circle).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensors_footprint_params (
    norad_id            integer PRIMARY KEY REFERENCES satellites(norad_id) ON DELETE CASCADE,
    fov_deg             real,        -- optical field of view (full angle)
    max_look_angle_deg  real,        -- off-nadir pointing limit
    swath_width_km      real,        -- SAR swath width
    swath_offset_km     real,        -- SAR side-look ground offset from nadir
    coverage_radius_km  real,        -- sigint/other broad coverage radius
    updated_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Geofences / choke points (Layer B dark-vessel watch, Layer E zones).
-- MultiPolygon in WGS84; cast to geography for containment math.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geofences (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL,                  -- e.g. 'Strait of Hormuz'
    category        text NOT NULL DEFAULT 'chokepoint'
                      CHECK (category IN ('chokepoint','exclusion','aoi','other')),
    -- Per-geofence dark-vessel sensitivity: how long an AIS gap before we flag (seconds).
    dark_gap_seconds integer NOT NULL DEFAULT 1800,
    geom            geometry(MultiPolygon, 4326) NOT NULL,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
