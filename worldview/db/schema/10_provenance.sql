-- WorldView :: 10_provenance.sql
-- Provenance / chain-of-custody (ticket H19.4.3). Every datum/insight must trace back to its
-- source, and every reconstruction must expose WHEN WorldView learned it vs WHEN it was true.
--
-- BITEMPORAL MODEL
-- ----------------
-- WorldView is bitemporal along two independent time axes:
--   * VALID TIME       — the row's `ts` (or `effective_from`/`effective_to` for interval rows):
--                        when the fact was true in the world. This is the 4th dimension the
--                        as-of-T reconstruction scrubs along (§8.2).
--   * TRANSACTION TIME — the row's `ingested_at`: when WorldView recorded the fact. Defaulted to
--                        now() so an INSERT that omits it stamps the write time automatically.
-- The (valid, transaction) pair IS the bitemporality — we do NOT invent synthetic valid_from/
-- valid_to ranges for the append-only position/event streams (their `ts` is the valid instant).
-- Explicit validity ranges live only on genuinely stateful-interval rows: NOTAMs and strike
-- zones already carry effective_from/effective_to; dark-vessel events carry last_seen_ts..ts.
--
-- SOURCE LINEAGE
-- --------------
-- The `source` column already present on most stream tables is the lineage handle (feed name /
-- provider / 'terrestrial' | 'satellite' | ...). Tables that lacked one get it here, defaulting
-- to the 'unknown' sentinel so historic rows and source-less writers keep working.
--
-- This migration is ADDITIVE and IDEMPOTENT: every change is `ADD COLUMN IF NOT EXISTS` (or
-- `CREATE ... IF NOT EXISTS`), so re-applying is safe and existing ingestion writers that omit
-- the new columns keep working via the DEFAULTs. Run after 00..09. TimescaleDB/PostGIS-valid.

-- ===========================================================================
-- TRANSACTION TIME — add `ingested_at` (write/record time) to every stream/event table that
-- lacks it. Defaulted to now() so existing INSERTs (which never name the column) still land.
-- NOT NULL is safe because the DEFAULT fills it on every insert and existing rows are backfilled.
-- ===========================================================================

ALTER TABLE adsb_positions
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE ais_positions
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE satellite_ephemeris
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE gps_jamming
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE internet_outages
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE dark_vessel_events
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE geopolitical_events
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE recon_windows
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

-- NOTAMs and strike zones already carry `created_at` (their record time) but we add the
-- canonical `ingested_at` too so the provenance projection is uniform across every layer.
ALTER TABLE notams
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE strike_zones
    ADD COLUMN IF NOT EXISTS ingested_at timestamptz NOT NULL DEFAULT now();

-- ===========================================================================
-- SOURCE LINEAGE — ensure every stream/event table has a `source`. Most already do (02/03/05/06
-- declare it NOT NULL or with a feed default); only the tables missing one get it here, defaulted
-- to 'unknown' so existing rows and source-less writers keep working.
-- ===========================================================================

ALTER TABLE satellite_ephemeris
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'unknown';

ALTER TABLE dark_vessel_events
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'unknown';

ALTER TABLE recon_windows
    ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'unknown';

-- ===========================================================================
-- PROVENANCE PROJECTION — a read-only VIEW that UNIONs the last-known provenance per
-- (layer, entity_id) across the position/event streams. Each row exposes the source lineage,
-- the valid time (`ts`) and the transaction time (`ingested_at`) for the most recent datum of
-- an entity. Kept simple (one DISTINCT ON per layer) and TimescaleDB/PostGIS-valid: it only
-- reads scalar/time columns, no geometry. Callers that want point-in-time provenance should use
-- the parameterized `provenanceOf` repository (it filters `ts <= T`); this view is the
-- "latest known" convenience surface for dashboards / ad-hoc audit.
-- ===========================================================================

CREATE OR REPLACE VIEW provenance_latest AS
    SELECT DISTINCT ON (icao24)
        'adsb'::text AS layer, icao24::text AS entity_id, source, ts, ingested_at
    FROM adsb_positions
    ORDER BY icao24, ts DESC
  UNION ALL
    SELECT DISTINCT ON (mmsi)
        'ais'::text AS layer, mmsi::text AS entity_id, source, ts, ingested_at
    FROM ais_positions
    ORDER BY mmsi, ts DESC
  UNION ALL
    SELECT DISTINCT ON (norad_id)
        'tle'::text AS layer, norad_id::text AS entity_id, source, ts, ingested_at
    FROM satellite_ephemeris
    ORDER BY norad_id, ts DESC
  UNION ALL
    SELECT DISTINCT ON (h3_index)
        'ew'::text AS layer, h3_index::text AS entity_id, source, ts, ingested_at
    FROM gps_jamming
    ORDER BY h3_index, ts DESC
  UNION ALL
    SELECT DISTINCT ON (event_id)
        'context'::text AS layer, event_id::text AS entity_id, source, ts, ingested_at
    FROM geopolitical_events
    ORDER BY event_id, ts DESC;
