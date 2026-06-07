-- WorldView :: 11_ontology.sql
-- Ontology object/link/ACTION layer (ticket H19.4.1). The objects + links are a pure READ
-- projection of the relational System-of-Record (no tables of their own — see the backend
-- repositories/ontology.ts). What lives here is the WRITE side: an append-only AUDIT table that
-- records every ontology ACTION invocation (annotate / watch / future actions), plus an
-- annotations table holding the note CONTENT for the `annotate` action.
--
-- These are PLAIN tables (NOT hypertables): action audit volume is low and we want simple
-- monotonically-increasing surrogate keys + arbitrary point reads, not time-series compression.
--
-- CRITICAL TimescaleDB lesson (already broke CI once): do NOT `ALTER TABLE ... ADD COLUMN ...
-- DEFAULT now()` on the EXISTING compressed hypertables (adsb_positions / ais_positions /
-- satellite_ephemeris / gps_jamming) — TimescaleDB forbids a non-constant default once columnstore
-- is enabled (07_policies.sql turns it on). The tables below are created FRESH here (after 00..10),
-- so a DEFAULT now() on `ts` is fine. All DDL is IF NOT EXISTS and idempotent — safe to re-apply.

-- ===========================================================================
-- ontology_actions — the audit trail. One immutable row per action invocation. The backend writes
-- it via recordAction() (INSERT ... RETURNING) and reads it back via listActions() so "actions =
-- audited endpoints" is verifiable. `params`/`result` are jsonb (the action's input + outcome).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ontology_actions (
    id           bigserial   PRIMARY KEY,
    ts           timestamptz NOT NULL DEFAULT now(),     -- when the action ran (transaction time)
    actor        text,                                    -- who invoked it (from X-Actor header; nullable)
    object_type  text        NOT NULL,                    -- ontology object type (e.g. 'Aircraft')
    object_id    text        NOT NULL,                    -- the targeted object's id
    action       text        NOT NULL,                    -- action name (e.g. 'annotate', 'watch')
    params       jsonb       NOT NULL DEFAULT '{}'::jsonb,-- normalized action input
    result       jsonb,                                   -- action outcome (nullable until/if produced)
    source       text        NOT NULL DEFAULT 'api'       -- invocation channel (api | mcp | ...)
);

-- Audit reads are "trail for this object" and "recent across all objects": index both access paths.
CREATE INDEX IF NOT EXISTS ontology_actions_object_idx
    ON ontology_actions (object_type, object_id, ts DESC);
CREATE INDEX IF NOT EXISTS ontology_actions_ts_idx
    ON ontology_actions (ts DESC);

-- ===========================================================================
-- ontology_annotations — the note CONTENT for the `annotate` action. Separate from the audit row
-- (which records THAT the action happened): this is the readable note/tags attached to an object.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ontology_annotations (
    id           bigserial   PRIMARY KEY,
    ts           timestamptz NOT NULL DEFAULT now(),
    actor        text,
    object_type  text        NOT NULL,
    object_id    text        NOT NULL,
    note         text        NOT NULL,
    tags         jsonb       NOT NULL DEFAULT '[]'::jsonb
);

-- "Annotations on this object, newest first" is the dominant read.
CREATE INDEX IF NOT EXISTS ontology_annotations_object_idx
    ON ontology_annotations (object_type, object_id, ts DESC);
