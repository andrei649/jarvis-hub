-- WorldView :: 12_cases.sql
-- Collaborative CASE FILES (ticket H19.4.5 "Cases / annotations / multi-user"). Two (or more)
-- analysts work a shared case: a case groups MEMBERS (the collaborating actors + their in-case role),
-- ITEMS (ontology objects/events pinned into the case) and COMMENTS (the discussion thread). Every
-- MUTATING case operation is additionally appended to the existing tamper-evident ontology_actions
-- hash chain by the backend (objectType 'Case'), so the case history is auditable end-to-end — this
-- file only holds the case state; the audit trail reuses 11_ontology.sql's chain.
--
-- These are PLAIN tables (NOT hypertables): case volume is low and we want simple surrogate keys +
-- arbitrary point reads, not time-series compression.
--
-- CRITICAL TimescaleDB lesson (already broke CI once): do NOT `ALTER TABLE ... ADD COLUMN ...
-- DEFAULT now()` on the EXISTING compressed hypertables (adsb_positions / ais_positions /
-- satellite_ephemeris / gps_jamming) — TimescaleDB forbids a non-constant default once columnstore is
-- enabled (07_policies.sql turns it on). The tables below are created FRESH here (after 00..11), so a
-- DEFAULT now() is fine. All DDL is IF NOT EXISTS and idempotent — safe to re-apply.

-- ===========================================================================
-- cases — the case file header. `status` is a small lifecycle enum (open -> closed/archived).
-- `created_by` is the actor who opened it (from the request principal / X-Actor; nullable). The
-- members/items/comments below all FK to this id with ON DELETE CASCADE so deleting a case cleans up.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS cases (
    id          bigserial   PRIMARY KEY,
    title       text        NOT NULL,
    description text,
    status      text        NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'closed', 'archived')),
    created_by  text,                                     -- opening actor (nullable)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- "Recent cases first" is the dominant list read.
CREATE INDEX IF NOT EXISTS cases_created_at_idx
    ON cases (created_at DESC);

-- ===========================================================================
-- case_members — the in-case collaboration layer: which actors are on the case and their case role
-- (owner / collaborator / viewer). This is SEPARATE from the API-level RBAC permission (which gates
-- whether a principal can touch the case API at all); membership records WHO is collaborating. PK on
-- (case_id, actor) so an actor appears at most once per case (re-add is an idempotent upsert).
-- ===========================================================================
CREATE TABLE IF NOT EXISTS case_members (
    case_id  bigint      NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    actor    text        NOT NULL,
    role     text        NOT NULL DEFAULT 'collaborator'
                         CHECK (role IN ('owner', 'collaborator', 'viewer')),
    added_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, actor)
);

-- "Members of this case" — the PK already btrees (case_id, actor), covering the by-case lookup.

-- ===========================================================================
-- case_items — ontology objects/events pinned into the case. (object_type, object_id) references an
-- ontology object the SAME way ontology_actions/ontology_annotations do (by type+id, not a hard FK —
-- ontology objects are a projection, not a single table). `note` is an optional per-item annotation.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS case_items (
    id          bigserial   PRIMARY KEY,
    case_id     bigint      NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    object_type text        NOT NULL,                     -- ontology object type (e.g. 'Aircraft')
    object_id   text        NOT NULL,                     -- the pinned object's id
    note        text,                                     -- optional per-item note
    added_by    text,                                     -- actor who pinned it (nullable)
    added_at    timestamptz NOT NULL DEFAULT now()
);

-- "Items of this case, newest first" is the dominant read.
CREATE INDEX IF NOT EXISTS case_items_case_idx
    ON case_items (case_id, added_at DESC);

-- ===========================================================================
-- case_comments — the case discussion thread. `actor` is the commenter (nullable); `body` is required.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS case_comments (
    id         bigserial   PRIMARY KEY,
    case_id    bigint      NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    actor      text,                                      -- commenting actor (nullable)
    body       text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- "Comments on this case, oldest first (thread order)" — index the access path.
CREATE INDEX IF NOT EXISTS case_comments_case_idx
    ON case_comments (case_id, created_at ASC);
