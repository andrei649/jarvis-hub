-- WorldView :: 06_context_intel.sql
-- Layer E — Contextual Intel. NOTAMs (airspace closures), strike zones, geopolitical events.
-- NOTAMs/strike zones are interval-valid (effective_from..effective_to), queried by containment
-- of the master time T. geopolitical_events is a sparse, event-driven hypertable.

-- ---------------------------------------------------------------------------
-- NOTAMs — airspace closures / restrictions. Active when effective_from <= T <= effective_to.
-- Regular table (not a hypertable): low volume, interval-keyed, not a firehose.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notams (
    id              text PRIMARY KEY,               -- NOTAM id, e.g. 'A1234/26'
    notam_type      text,                           -- e.g. 'airspace_closure', 'tfr', 'gps_outage'
    effective_from  timestamptz NOT NULL,
    effective_to    timestamptz,                    -- NULL = open-ended / until cancelled
    geom            geometry(Polygon, 4326) NOT NULL,
    lower_alt_m     real,                           -- vertical extent
    upper_alt_m     real,
    raw             text,                           -- original NOTAM text
    source          text NOT NULL DEFAULT 'faa',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Strike zones / exclusion areas — interval-valid, like NOTAMs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strike_zones (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text,
    effective_from  timestamptz NOT NULL,
    effective_to    timestamptz,
    geom            geometry(Polygon, 4326) NOT NULL,
    severity        smallint NOT NULL DEFAULT 1,    -- 1 (advisory) .. 5 (active strike)
    source          text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Geopolitical events — point/area incidents, sparse, time-stamped. Hypertable (7d chunks).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geopolitical_events (
    ts            timestamptz NOT NULL,
    event_id      text        NOT NULL,
    category      text        NOT NULL,             -- 'strike','protest','seizure','launch',...
    severity      smallint    NOT NULL DEFAULT 1,
    geom          geometry(Geometry, 4326) NOT NULL,-- point OR polygon depending on event
    source        text        NOT NULL,
    metadata      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (event_id, ts)
);

SELECT create_hypertable(
    'geopolitical_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);
