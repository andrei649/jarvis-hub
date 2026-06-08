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
-- The `source` column on every stream/event table is the lineage handle (feed name / provider /
-- 'terrestrial' | 'satellite' | ...). Tables whose writer doesn't supply one default it to the
-- 'unknown' sentinel so source-less writers and historic rows keep working.
--
-- WHERE THE PROVENANCE COLUMNS LIVE
-- ---------------------------------
-- `source` and `ingested_at` are declared in each table's base CREATE TABLE (files 02..09),
-- NOT added here by ALTER. This is deliberate: TimescaleDB forbids `ADD COLUMN ... DEFAULT <non-
-- constant>` (e.g. DEFAULT now()) once a hypertable has columnstore/compression enabled (07
-- enables it on adsb_positions / ais_positions / satellite_ephemeris / gps_jamming). Defining the
-- columns at table-creation time — before 07 runs — sidesteps that restriction entirely and keeps
-- a fresh schema apply (CI, `docker compose up`) clean. To back-fill these columns onto a PRE-
-- EXISTING columnstore database, do it in two steps (nullable add, then set the default):
--     ALTER TABLE <t> ADD COLUMN ingested_at timestamptz;          -- nullable add: allowed
--     ALTER TABLE <t> ALTER COLUMN ingested_at SET DEFAULT now();  -- catalog-only: allowed
--
-- This file is therefore a pure, additive PROJECTION layer: it only defines the read-only
-- `provenance_latest` view (below). It is idempotent (CREATE OR REPLACE) and safe to re-run.

-- ===========================================================================
-- PROVENANCE PROJECTION — a read-only VIEW that UNIONs the last-known provenance per
-- (layer, entity_id) across the position/event streams. Each row exposes the source lineage,
-- the valid time (`ts`) and the transaction time (`ingested_at`) for the most recent datum of
-- an entity. Kept simple (one DISTINCT ON per layer) and TimescaleDB/PostGIS-valid: it only
-- reads scalar/time columns, no geometry. Callers that want point-in-time provenance should use
-- the parameterized `provenanceOf` repository (it filters `ts <= T`); this view is the
-- "latest known" convenience surface for dashboards / ad-hoc audit.
--
-- COST / NOT A HOT PATH. Each DISTINCT ON arm scans the FULL history hypertable for its layer
-- (no ts bound, no entity filter) to find every entity's newest row — i.e. cost is O(all rows),
-- growing without limit as history accumulates. This is an AD-HOC / AUDIT CONVENIENCE only: do
-- NOT wire it into any request/hot path (map reads, reconstruction frames, per-entity lookups).
-- Hot, point-in-time provenance MUST go through the parameterized `provenanceOf` repository,
-- which bounds the scan with `ts <= T` + an entity filter and is index-backed.
-- ===========================================================================

-- Each UNION arm is parenthesized so its own `DISTINCT ON (...) ... ORDER BY` binds to that arm
-- (an un-parenthesized trailing ORDER BY would attach to the whole UNION instead — a syntax error
-- with the per-arm DISTINCT ON). The outer view is unordered; callers sort as needed.
CREATE OR REPLACE VIEW provenance_latest AS
    (SELECT DISTINCT ON (icao24)
        'adsb'::text AS layer, icao24::text AS entity_id, source, ts, ingested_at
    FROM adsb_positions
    ORDER BY icao24, ts DESC)
  UNION ALL
    (SELECT DISTINCT ON (mmsi)
        'ais'::text AS layer, mmsi::text AS entity_id, source, ts, ingested_at
    FROM ais_positions
    ORDER BY mmsi, ts DESC)
  UNION ALL
    (SELECT DISTINCT ON (norad_id)
        'tle'::text AS layer, norad_id::text AS entity_id, source, ts, ingested_at
    FROM satellite_ephemeris
    ORDER BY norad_id, ts DESC)
  UNION ALL
    (SELECT DISTINCT ON (h3_index)
        'ew'::text AS layer, h3_index::text AS entity_id, source, ts, ingested_at
    FROM gps_jamming
    ORDER BY h3_index, ts DESC)
  UNION ALL
    (SELECT DISTINCT ON (event_id)
        'context'::text AS layer, event_id::text AS entity_id, source, ts, ingested_at
    FROM geopolitical_events
    ORDER BY event_id, ts DESC);
