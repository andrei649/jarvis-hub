-- WorldView lakehouse :: DuckDB query layer (ticket H19.5.3).
--
-- Proves the "raw cold queryable" AC: query the Parquet lake that the Kafka Connect
-- S3 sink writes to MinIO, directly with DuckDB — no Postgres, no extra ETL.
--
-- RUN:
--   docker compose -f docker-compose.yml -f deploy/lakehouse/docker-compose.lakehouse.yml up -d
--   # let the sink flush at least one Parquet file (flush.size / rotate.interval.ms), then:
--   duckdb < deploy/lakehouse/queries.sql
--   # or open an interactive shell:  duckdb  -init deploy/lakehouse/queries.sql
--
-- Requires DuckDB >= 0.10 (httpfs + parquet extensions ship with it).

-- 1) Talk S3 to MinIO ---------------------------------------------------------
INSTALL httpfs;
LOAD httpfs;

SET s3_endpoint = 'localhost:9000';   -- MinIO S3 API (host port from the compose)
SET s3_url_style = 'path';            -- MinIO needs path-style addressing
SET s3_use_ssl = false;               -- local MinIO is plain HTTP
SET s3_region = 'us-east-1';
SET s3_access_key_id = 'worldview';
SET s3_secret_access_key = 'worldview-secret';

-- NOTE: from *inside* a container on the worldview network, use s3_endpoint='minio:9000'.

-- 2) Smoke test: how many raw cold ADS-B rows are in the lake? -----------------
SELECT count(*) AS adsb_rows
FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet');

-- 3) Peek at the raw envelope (Connect lands the JSON value as Parquet columns) -
SELECT *
FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet')
LIMIT 20;

-- 4) Cold long-range analytics across the whole firehose ----------------------
-- Per-domain record counts straight off the lake (each topic = one OSINT domain).
SELECT 'adsb'    AS domain, count(*) AS n FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet')
UNION ALL SELECT 'ais',    count(*) FROM read_parquet('s3://worldview-lake/topics/osint.ais/**/*.parquet')
UNION ALL SELECT 'tle',    count(*) FROM read_parquet('s3://worldview-lake/topics/osint.tle/**/*.parquet')
UNION ALL SELECT 'ew',     count(*) FROM read_parquet('s3://worldview-lake/topics/osint.ew/**/*.parquet')
UNION ALL SELECT 'context',count(*) FROM read_parquet('s3://worldview-lake/topics/osint.context/**/*.parquet')
UNION ALL SELECT 'recon',  count(*) FROM read_parquet('s3://worldview-lake/topics/osint.recon/**/*.parquet')
ORDER BY domain;

-- 5) Example time-range scan on cold ADS-B beyond the TSDB retention window ----
-- (The envelope carries an event timestamp; adjust the field name to your envelope:
--  design doc §4 uses `ts` / `event_ts`. DuckDB reads it as the Parquet column.)
-- SELECT
--   date_trunc('hour', CAST(ts AS TIMESTAMP)) AS hour,
--   count(*)                                  AS positions,
--   count(DISTINCT icao24)                    AS aircraft
-- FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet')
-- WHERE CAST(ts AS TIMESTAMP) >= TIMESTAMP '2026-01-01'
-- GROUP BY 1
-- ORDER BY 1;

-- 6) Create a persistent DuckDB view over the lake for repeated cold queries ---
-- CREATE OR REPLACE VIEW lake_adsb AS
--   SELECT * FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet');
-- SELECT count(*) FROM lake_adsb;
