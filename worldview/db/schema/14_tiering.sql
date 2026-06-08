-- WorldView :: 14_tiering.sql  (ticket H19.1.7 — Tiered storage broker + retention ops)
-- ===========================================================================
-- Explicit HOT -> WARM -> COLD storage lifecycle per OSINT layer. This file
-- EXTENDS 07_policies.sql (which already enables columnstore compression + a
-- first cut of retention + the continuous aggregates). 14 is the single place
-- that documents and tunes the *tiering* per layer's velocity. It does NOT
-- re-declare what 07 already owns where 07 already sets the right value; where a
-- value here differs from 07 the comment says so and `if_not_exists => TRUE`
-- keeps it a no-op on an already-installed policy (07 wins on first boot, this
-- file is the authoritative reference + the place to retune by re-adding after a
-- `remove_*_policy`).
--
-- TIER MODEL
--   HOT   = most-recent, UNCOMPRESSED chunks. Row store, fast point-writes +
--           random reads. Lives in TimescaleDB. Size = velocity x hot window.
--   WARM  = compressed COLUMNSTORE chunks (07 sets timescaledb.compress +
--           compress_segmentby/orderby per table). ~10-20x smaller, still
--           queryable in-place. `add_compression_policy(<table>, <age>)` moves a
--           chunk HOT->WARM once it is older than <age>.
--   COLD  = the lakehouse Parquet lake (deploy/lakehouse/, s3://worldview-lake).
--           Every raw envelope is streamed to Parquet from Kafka AS IT ARRIVES,
--           independent of the OLTP writers. So when `add_retention_policy`
--           DROPS a chunk out of TimescaleDB, the full-fidelity record still
--           lives in the lake and is queryable with DuckDB. COLD is not a
--           TimescaleDB move here — it is "already there", and retention is what
--           releases the OLTP storage. The continuous aggregates
--           (adsb_positions_1m / ais_positions_1m, 07_policies.sql) are separate
--           hypertables that SURVIVE retention, so long-range zoomed-out
--           scrubbing keeps working after the raw chunks are gone.
--
-- CRITICAL (the columnstore restriction that broke CI once): this file only
-- ADDS / TUNES POLICIES. It does NOT run `ALTER TABLE ... ADD COLUMN ...
-- DEFAULT ...` on any compressed hypertable — that is disallowed on the
-- columnstore and is explicitly avoided here. No schema/column changes live in
-- this file, only policy DDL.
--
-- All statements are idempotent (`if_not_exists => TRUE`) and safe to re-run.
-- ===========================================================================


-- ===========================================================================
-- WARM tier — compression policies (HOT -> WARM age, per layer velocity).
-- 07_policies.sql already SET (timescaledb.compress, ...) and added compression
-- policies. We confirm/tune the HOT->WARM age per layer here. Higher-velocity
-- layers compress sooner (shorter hot window => less uncompressed bloat); intel
-- layers compress later (small, often re-read while warm-ish).
--
--   adsb_positions       2 days   (1h chunks, firehose: short hot window)
--   ais_positions        2 days   (6h chunks, high velocity)
--   satellite_ephemeris  7 days   (1d chunks, materialized propagation)
--   gps_jamming          7 days   (1d chunks, bucketed H3 aggregate)
--
-- These match 07. The add_* calls below are idempotent no-ops when 07 already
-- installed them; they are kept here so 14 is the complete, self-describing
-- tiering manifest (and the retune point if a window changes).
-- ===========================================================================

SELECT add_compression_policy('adsb_positions',      INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('ais_positions',       INTERVAL '2 days', if_not_exists => TRUE);
SELECT add_compression_policy('satellite_ephemeris', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('gps_jamming',         INTERVAL '7 days', if_not_exists => TRUE);

-- --- Intel-layer columnstore (NOT enabled in 07) -------------------------------
-- dark_vessel_events / geopolitical_events / recon_windows are low-velocity
-- intelligence records (7d / 7d / 1d chunks). They are kept FOREVER (no
-- retention, see below), so compressing their old chunks is pure win: it shrinks
-- the permanently-resident footprint while keeping them queryable. 07 does not
-- touch them, so we enable the columnstore here. ALTER TABLE ... SET (compress)
-- only sets table options — it is NOT an ADD COLUMN and is allowed pre-policy.
-- segmentby = the natural entity key, orderby = the time column DESC.

ALTER TABLE dark_vessel_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'mmsi',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('dark_vessel_events', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE geopolitical_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'category',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('geopolitical_events', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE recon_windows SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'aoi_id',
    timescaledb.compress_orderby   = 't_ingress DESC'
);
SELECT add_compression_policy('recon_windows', INTERVAL '30 days', if_not_exists => TRUE);


-- ===========================================================================
-- COLD tier release — retention policies (drop raw chunks; cold copy lives in
-- the lake). Per-layer ages by velocity + intel value:
--
--   adsb_positions        90 days   highest velocity -> shortest OLTP window
--   ais_positions        180 days   high velocity
--   satellite_ephemeris  180 days   medium (re-derivable from tle_catalog)
--   gps_jamming          365 days   medium, long analytical tail
--   internet_outages     365 days   low volume, long analytical tail
--   recon_windows        730 days   intel: keep 2y of predicted/observed passes
--   dark_vessel_events     NONE     intelligence record — never auto-dropped
--   geopolitical_events    NONE     intelligence record — never auto-dropped
--
-- The first five match 07_policies.sql (idempotent no-ops if 07 installed them).
-- recon_windows retention is ADDED here (09 created the hypertable; 07 predates
-- it and never set one). dark_vessel_events / geopolitical_events keep NO
-- retention — but now DO get compressed (above), so they stay small forever.
--
-- Dropped raw chunks remain queryable in COLD (the lake) and, for adsb/ais, also
-- summarized in the surviving continuous aggregates.
-- ===========================================================================

SELECT add_retention_policy('adsb_positions',      INTERVAL '90 days',  if_not_exists => TRUE);
SELECT add_retention_policy('ais_positions',       INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('satellite_ephemeris', INTERVAL '180 days', if_not_exists => TRUE);
SELECT add_retention_policy('gps_jamming',         INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('internet_outages',    INTERVAL '365 days', if_not_exists => TRUE);
SELECT add_retention_policy('recon_windows',       INTERVAL '730 days', if_not_exists => TRUE);
-- dark_vessel_events + geopolitical_events: intentionally NO retention (intel).
-- tle_catalog is a plain table (not a hypertable): no chunk retention; the raw
-- TLEs are the audit trail for re-deriving satellite_ephemeris and are kept.


-- ===========================================================================
-- COLD continuous-aggregate retention (optional, currently OFF).
-- The 1-minute rollups in 07 are themselves hypertables and could carry their
-- own (much longer) retention if the long-range scrub horizon is ever bounded.
-- Left OFF on purpose: the rollups are tiny (one row/entity/minute) and are the
-- ONLY thing that survives raw retention for zoomed-out scrubbing. To bound
-- them, uncomment with a horizon well past the raw windows above, e.g.:
--   SELECT add_retention_policy('adsb_positions_1m', INTERVAL '3 years', if_not_exists => TRUE);
--   SELECT add_retention_policy('ais_positions_1m',  INTERVAL '3 years', if_not_exists => TRUE);
-- Also consider compressing the rollups for an even smaller long-range tier.


-- ===========================================================================
-- ENTERPRISE / TimescaleDB-Cloud tiered_storage — DOCUMENTATION ONLY.
-- ---------------------------------------------------------------------------
-- The OSS `timescale/timescaledb-ha:pg16` image used by this project does NOT
-- ship the managed object-storage tiering feature. The OSS-correct COLD tier is
-- therefore the lakehouse lake (above + deploy/lakehouse/), and retention is
-- what releases OLTP storage.
--
-- On TimescaleDB Cloud / Enterprise, native tiered storage would slot in
-- BETWEEN warm and "drop": instead of `add_retention_policy` deleting an aged
-- chunk, `add_tiering_policy` would MOVE it to the managed S3 object tier where
-- it stays transparently queryable through the same SQL (a "tiered" chunk reads
-- back via the access node), e.g.:
--
--   -- one-time, managed-service only:
--   --   ALTER DATABASE worldview SET timescaledb.enable_tiered_reads = 'on';
--   -- move chunks older than the WARM window to the object tier instead of
--   -- dropping them; reads transparently span local + tiered chunks:
--   --   SELECT add_tiering_policy('adsb_positions',      INTERVAL '90 days');
--   --   SELECT add_tiering_policy('ais_positions',       INTERVAL '180 days');
--   --   SELECT add_tiering_policy('satellite_ephemeris', INTERVAL '180 days');
--   --   SELECT add_tiering_policy('gps_jamming',         INTERVAL '365 days');
--   -- (and DROP the matching add_retention_policy calls so chunks tier instead
--   --  of being deleted; tiered chunks can still be dropped later if desired).
--
-- Migration note: where this OSS build uses (retention -> lake -> DuckDB), the
-- managed build would use (add_tiering_policy -> native object tier -> same
-- SQL), and the per-layer ages above are the exact thresholds to reuse. The
-- lake remains useful regardless as the raw, engine-agnostic archive.
-- ===========================================================================


-- ===========================================================================
-- OPERATIONS — inspect the tiering state. Read-only, safe to run anytime.
-- ---------------------------------------------------------------------------
-- All configured policy jobs (compression + retention + cagg refresh):
--   SELECT job_id, application_name, schedule_interval, hypertable_name, config
--     FROM timescaledb_information.jobs
--    WHERE application_name LIKE '%Compression%'
--       OR application_name LIKE '%Retention%'
--    ORDER BY hypertable_name;
--
-- Per-hypertable HOT(uncompressed) vs WARM(compressed) size + ratio:
--   SELECT hypertable_name,
--          pg_size_pretty(before_compression_total_bytes) AS hot_total,
--          pg_size_pretty(after_compression_total_bytes)  AS warm_total
--     FROM hypertable_compression_stats('adsb_positions');
--
-- Chunk-level tier (is a chunk WARM yet?):
--   SELECT chunk_name, range_start, range_end, is_compressed
--     FROM timescaledb_information.chunks
--    WHERE hypertable_name = 'adsb_positions'
--    ORDER BY range_start DESC;
-- ===========================================================================
