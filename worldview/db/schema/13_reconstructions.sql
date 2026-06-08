-- WorldView :: 13_reconstructions.sql
-- SAVED RECONSTRUCTIONS + shareable replay (tickets H19.2.7 "Event reconstruction + shareable replay
-- export" and H19.4.6 "Export / reporting"). A reconstruction is a TEMPORALLY-BOUNDED, viewport-bounded
-- request to re-derive layered as-of-T frames from history: a small saved HANDLE (title + params) that
-- is the SHAREABLE LINK. The backend never freezes a copy of the frames here — replaying a saved
-- reconstruction RE-DERIVES the frames from the history hypertables using the SAME params, so the
-- export is REPRODUCIBLE (same params -> same frame timestamps -> same as-of-T reads). Creating a
-- reconstruction is also appended to the existing tamper-evident ontology_actions hash chain by the
-- backend (objectType 'Reconstruction'), so the saved handle is auditable end-to-end.
--
-- `params` jsonb shape (validated in the backend): { from, to, stepSeconds, bbox?, layers[] } where
-- from/to are UNIX seconds (UTC instants), stepSeconds the frame cadence, bbox an optional viewport
-- {w,s,e,n}, and layers[] the requested history layers (adsb/ais/tle/ew/context).
--
-- This is a PLAIN table (NOT a hypertable): reconstruction volume is low and we want a simple surrogate
-- key + arbitrary point reads, not time-series compression.
--
-- CRITICAL TimescaleDB lesson (already broke CI once): do NOT `ALTER TABLE ... ADD COLUMN ... DEFAULT
-- now()` on the EXISTING compressed hypertables. This table is created FRESH here (after 00..12), so a
-- DEFAULT now() is fine. All DDL is IF NOT EXISTS and idempotent — safe to re-apply.

-- ===========================================================================
-- reconstructions — the saved, shareable replay handle. `params` carries the full re-derivation recipe
-- (from/to/stepSeconds/bbox?/layers[]); `created_by` is the actor who saved it (nullable, from the
-- request principal / X-Actor). The frames are NOT stored — they are re-derived from history on export.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS reconstructions (
    id         bigserial   PRIMARY KEY,
    title      text,                                       -- optional human label
    params     jsonb       NOT NULL,                       -- { from, to, stepSeconds, bbox?, layers[] }
    created_by text,                                       -- saving actor (nullable)
    created_at timestamptz NOT NULL DEFAULT now()
);

-- "Recent reconstructions first" is the dominant list read.
CREATE INDEX IF NOT EXISTS reconstructions_created_at_idx
    ON reconstructions (created_at DESC);
