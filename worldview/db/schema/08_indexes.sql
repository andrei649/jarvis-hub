-- WorldView :: 08_indexes.sql
-- Spatial (GiST) and "as-of T" (composite) indexes.
--
-- TimescaleDB already auto-creates a (time DESC) index on each hypertable (plus per-chunk
-- exclusion), so the temporal access path needs no extra (e.g. BRIN) index; and the
-- PRIMARY KEY (entity_id, ts) backs the DISTINCT ON (entity_id ... ORDER BY ts DESC)
-- reconstruction path (§8.2) directly. The indexes below add the spatial + scan paths.

-- ---------------------------------------------------------------------------
-- GiST spatial indexes — back viewport (bounding-box) queries from the map.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS adsb_positions_geom_gist     ON adsb_positions      USING gist (geom);
CREATE INDEX IF NOT EXISTS ais_positions_geom_gist      ON ais_positions       USING gist (geom);
CREATE INDEX IF NOT EXISTS sat_ephemeris_geom_gist      ON satellite_ephemeris USING gist (geom);
CREATE INDEX IF NOT EXISTS sat_ephemeris_footprint_gist ON satellite_ephemeris USING gist (footprint);
CREATE INDEX IF NOT EXISTS gps_jamming_geom_gist        ON gps_jamming         USING gist (h3_geom);
CREATE INDEX IF NOT EXISTS internet_outages_geom_gist   ON internet_outages    USING gist (region_geom);
CREATE INDEX IF NOT EXISTS notams_geom_gist             ON notams              USING gist (geom);
CREATE INDEX IF NOT EXISTS strike_zones_geom_gist       ON strike_zones        USING gist (geom);
CREATE INDEX IF NOT EXISTS geopolitical_events_geom_gist ON geopolitical_events USING gist (geom);
CREATE INDEX IF NOT EXISTS geofences_geom_gist          ON geofences           USING gist (geom);

-- ---------------------------------------------------------------------------
-- Interval-containment scans for Layer E (effective_from <= T <= effective_to).
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS notams_effective_idx
    ON notams (effective_from, effective_to);
CREATE INDEX IF NOT EXISTS strike_zones_effective_idx
    ON strike_zones (effective_from, effective_to);

-- ---------------------------------------------------------------------------
-- Partial indexes for the dark-vessel watchboard: only currently-dark vessels.
-- ---------------------------------------------------------------------------
-- Per-geofence watchboard queries (kept: the geofence-scoped readers use this).
CREATE INDEX IF NOT EXISTS dark_vessel_active_idx
    ON dark_vessel_events (geofence_id, ts DESC)
    WHERE status = 'dark';

-- as-of-T context read (history.ts contextAsOf): DISTINCT ON (mmsi) ... ORDER BY mmsi, ts DESC,
-- filtered to dark only — without geofence_id — so it needs an (mmsi, ts DESC) partial index to
-- be index-backed (the geofence_id-leading index above can't serve the mmsi-leading scan).
CREATE INDEX IF NOT EXISTS dark_vessel_active_by_mmsi_idx
    ON dark_vessel_events (mmsi, ts DESC)
    WHERE status = 'dark';

-- ---------------------------------------------------------------------------
-- Military-only flight filter (common OSINT view): partial index keeps it tiny.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS adsb_military_idx
    ON adsb_positions (ts DESC)
    WHERE is_military = true;
