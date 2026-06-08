# WorldView — lakehouse offload (ticket H19.5.3)

Lands the OSINT Redpanda topics as **Parquet on S3-compatible object storage (MinIO)** so
the OLTP store stays bounded. TimescaleDB keeps **hot/warm** state under the retention +
compression policies in `db/schema/07_policies.sql`; the **raw cold firehose** is captured
here in the lake and is queryable on demand with **DuckDB** — no Postgres bloat.

```
 Redpanda topics ──► Kafka Connect (Confluent S3 sink, Parquet) ──► MinIO  s3://worldview-lake
   osint.adsb                                                          │
   osint.ais                                                           ▼
   osint.tle                                                     DuckDB (httpfs + parquet)
   osint.ew                                                      "raw cold queryable"
   osint.context
   osint.recon
```

## Components

| Service | Image | Role |
| --- | --- | --- |
| `minio` | `minio/minio:RELEASE.2024-06-13T22-53-53Z` | S3-compatible object store (`s3://worldview-lake`) |
| `minio-init` | `minio/mc:RELEASE.2024-06-12T14-34-03Z` | one-shot: creates the bucket |
| `kafka-connect` | `confluentinc/cp-kafka-connect:7.6.1` | Connect runtime (Confluent S3 sink ships in-image) |
| `connect-init` | `curlimages/curl:8.8.0` | one-shot: registers the S3 Parquet sink connectors |

The S3 sink (`io.confluent.connect.s3.S3SinkConnector`) with
`io.confluent.connect.s3.format.parquet.ParquetFormat` is the robust, runnable choice: a
maintained connector that batches topic records and writes **snappy-compressed Parquet**
straight to MinIO. The AWS SDK is pointed at MinIO via `store.url` + `s3.path.style.access`.

## Bucket layout

Default partitioner, `topics.dir=topics`:

```
s3://worldview-lake/topics/<topic>/partition=<p>/<topic>+<p>+<startOffset>.parquet
```

Examples:

```
s3://worldview-lake/topics/osint.adsb/partition=0/osint.adsb+0+0000000000.parquet
s3://worldview-lake/topics/osint.ais/partition=0/osint.ais+0+0000010000.parquet
s3://worldview-lake/topics/osint.recon/partition=0/osint.recon+0+0000000000.parquet
```

Two connectors split the firehose by volume/latency profile:

| Connector config | Topics | `flush.size` | `rotate.interval.ms` |
| --- | --- | --- | --- |
| `connectors/osint-telemetry-s3-parquet.json` | `osint.adsb,osint.ais,osint.tle,osint.ew` | 10000 | 60000 |
| `connectors/osint-intel-s3-parquet.json` | `osint.context,osint.recon` | 1000 | 120000 |

A file is rotated to the lake when **either** `flush.size` records accumulate **or**
`rotate.interval.ms` of stream time elapses (so low-volume topics still land files), bounded
by `rotate.schedule.interval.ms` of wall-clock time.

## Run

```bash
cd worldview
docker compose up -d                                   # core infra (redpanda must be healthy)
docker compose -f docker-compose.yml \
  -f deploy/lakehouse/docker-compose.lakehouse.yml up -d
```

- MinIO S3 API: http://localhost:9000  (`worldview` / `worldview-secret`)
- MinIO console: http://localhost:9001
- Connect REST: http://localhost:8083 — list/inspect connectors:

```bash
curl -s localhost:8083/connectors | jq
curl -s localhost:8083/connectors/osint-telemetry-s3-parquet/status | jq
```

`connect-init` registers both connectors with idempotent `PUT /connectors/<name>/config`,
so re-running `up` just re-applies the config.

## Query the lake with DuckDB

Once at least one Parquet file has been flushed (give the firehose a minute, or wait
`rotate.interval.ms`):

```bash
duckdb < deploy/lakehouse/queries.sql
```

The key pattern (full script in `queries.sql`):

```sql
INSTALL httpfs; LOAD httpfs;
SET s3_endpoint='localhost:9000';
SET s3_url_style='path';
SET s3_use_ssl=false;
SET s3_access_key_id='worldview';
SET s3_secret_access_key='worldview-secret';

SELECT count(*) FROM read_parquet('s3://worldview-lake/topics/osint.adsb/**/*.parquet');
```

From inside a container on the worldview network use `s3_endpoint='minio:9000'`.

## How it pairs with TimescaleDB retention (hot vs cold)

`db/schema/07_policies.sql` defines the OLTP lifecycle:

- **compression** kicks in after 2–7 days (columnar, still queryable in TSDB);
- **retention** drops raw chunks after 90d (ADS-B) / 180d (AIS, ephemeris) / 365d (jamming,
  outages); continuous aggregates (`adsb_positions_1m`, `ais_positions_1m`) survive for
  long-range zoomed-out scrubbing.

The lake is the **cold tier that sits underneath** that: every raw envelope is captured to
Parquet **as it streams** (from Kafka, independent of the OLTP writers), so when a raw chunk
ages out of TimescaleDB the full-fidelity record is still in `s3://worldview-lake` and
queryable with DuckDB. Net effect: **hot in TSDB (bounded by retention), cold in the lake
(unbounded, cheap, queryable)** — the OLTP store never has to hold the whole history to
keep it.

## Image pins

| Image | Tag |
| --- | --- |
| minio/minio | RELEASE.2024-06-13T22-53-53Z |
| minio/mc | RELEASE.2024-06-12T14-34-03Z |
| confluentinc/cp-kafka-connect | 7.6.1 |
| curlimages/curl | 8.8.0 |

## App-side TODOs / notes

- **Sink runs off Kafka, not the OLTP writers** — no app change is required to capture the
  lake; the connectors subscribe to the same `osint.*` topics the writers consume. The sink
  uses its own Connect consumer group (`connect-worldview-lakehouse-connect`), independent of
  `live-writer` / `history-writer` / `recon-writer`, so it does not steal their offsets.
- **Envelope timestamp column** — `queries.sql` time-range examples assume the envelope's
  event-time field (design doc §4: `ts` / `event_ts`). Confirm the exact JSON key and adjust
  the DuckDB casts. TODO if a different field name is used.
- **Time-based partitioning (optional upgrade)** — swap `DefaultPartitioner` for
  `TimeBasedPartitioner` (`path.format=YYYY/MM/dd/HH`, `partition.duration.ms`) in the
  connector JSON to get Hive-style date partitions and partition pruning in DuckDB.
