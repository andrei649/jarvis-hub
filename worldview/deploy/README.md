# WorldView — deploy/ (local-runnable infra add-ons)

Runnable Docker Compose stacks that layer on top of the core infra in
`worldview/docker-compose.yml` (Redpanda + TimescaleDB + Redis). They run on a laptop;
the at-scale SLO numbers in the design docs require real hardware, but the **stack itself
runs locally unchanged** — same images, same config.

All compose files here are written to be run **from the `worldview/` project directory**
so they share the main project's network and can reach `redpanda` / `timescaledb` /
`redis` / `api` by service name.

## What's here

| Path | Stack | Ticket |
| --- | --- | --- |
| `observability/` | OTel Collector + Prometheus + Grafana + golden-signal dashboards + lag alarm | H19.5.5 |
| `observability/RUNBOOK.md` | Golden-signal runbook (dashboards, alarms, first response) | H19.5.5 |
| `tiles/` | Martin vector-tile server (MVT from PostGIS point tables) | H19.5.1 (server side) |
| `lakehouse/` | MinIO + Kafka Connect S3/Parquet sink (raw cold lake) + DuckDB query layer | H19.5.3 |
| `k8s/` | Ingestion consumer Deployments + KEDA `ScaledObject`s (lag-scaled) | H19.1.5 |
| `tiering/` | HOT→WARM→COLD storage lifecycle docs (SQL in `db/schema/14_tiering.sql`; cold = lakehouse) | H19.1.7 |
| `dr/` | DR TimescaleDB streaming replica + Redpanda topic mirror + RPO/RTO game-day drill | H19.5.6 |

## Run: observability

```bash
cd worldview
docker compose up -d   # core infra first
docker compose -f docker-compose.yml -f deploy/observability/docker-compose.observability.yml up -d
```

- Grafana: http://localhost:3001 (admin / admin) → folder **WorldView**
- Prometheus: http://localhost:9090 (Status → Targets, Alerts)
- OTLP ingest: `otel-collector:4317` (gRPC) / `:4318` (HTTP)

Dashboards: **API Golden Signals**, **Ingestion & Consumer Lag**, **Live / WebSocket Path**.
Lag alarm: `KafkaConsumerLagHigh` (>50k for 5m) + `KafkaConsumerLagCritical` (>250k for 10m).
See `observability/RUNBOOK.md`.

## Run: tiles

```bash
cd worldview
docker compose -f docker-compose.yml -f deploy/tiles/docker-compose.tiles.yml up -d
```

- Catalog: http://localhost:3002/catalog
- Tile URL template: `http://localhost:3002/{table}/{z}/{x}/{y}`
  - `http://localhost:3002/adsb_positions/{z}/{x}/{y}`
  - `http://localhost:3002/ais_positions/{z}/{x}/{y}`

## Run: lakehouse (H19.5.3)

```bash
cd worldview
docker compose up -d   # core infra first (redpanda must be healthy)
docker compose -f docker-compose.yml -f deploy/lakehouse/docker-compose.lakehouse.yml up -d
```

- MinIO S3 API: http://localhost:9000 (`worldview` / `worldview-secret`), console: http://localhost:9001
- Kafka Connect REST: http://localhost:8083 (`/connectors`)
- Lake bucket layout: `s3://worldview-lake/topics/<topic>/partition=<p>/...parquet`
- Query the cold lake with DuckDB: `duckdb < deploy/lakehouse/queries.sql`

Captures the `osint.*` firehose as Parquet (Confluent S3 sink) so TimescaleDB stays bounded:
hot/warm in TSDB (retention in `db/schema/07_policies.sql`), raw cold in the lake. See
`lakehouse/README.md`.

## Tiered storage (H19.1.7)

No compose stack — tiering is policy DDL (`db/schema/14_tiering.sql`, applied with
the rest of the schema) plus the existing `lakehouse/` lake as the COLD tier.

- **HOT** = recent uncompressed chunks (TimescaleDB row store).
- **WARM** = compressed columnstore chunks (TimescaleDB, ~10-20x smaller, queryable).
- **COLD** = Parquet in `s3://worldview-lake` (already streamed from Kafka), queryable via DuckDB.

`14_tiering.sql` extends `07_policies.sql`: confirms per-layer HOT→WARM compress
ages (adsb/ais 2d, ephemeris/jamming 7d), adds columnstore + 30d compression for
the three intel layers, and sets WARM→drop retention per layer (adsb 90d, ais/
ephemeris 180d, jamming/outages 365d, recon 730d; dark-vessel + geopolitical kept
forever). Continuous aggregates survive retention for long-range scrubbing. All
DDL idempotent; no `ALTER ... ADD COLUMN` on compressed tables. The enterprise
`add_tiering_policy` path is documented (OSS image lacks managed object-tiering).
See `tiering/README.md` for the per-layer table + storage-size math.

## DR: replica + Kafka mirror + game-day (H19.5.6)

```bash
cd worldview
docker compose up -d                                   # primary infra first
docker compose -f docker-compose.yml -f deploy/dr/docker-compose.dr.yml up -d
deploy/dr/game-day.sh             # checks RPO (lag) + mirror, no promotion
deploy/dr/game-day.sh --promote   # also promotes the replica + measures RTO
```

- DR TimescaleDB streaming replica: `localhost:5433` (read-only hot standby).
- DR Redpanda mirror target: `localhost:9093` (`osint.*` topics mirrored).
- Targets: RPO ≤ 5 min (replication lag), RTO ≤ 30 min (promotion time).

**Primary-side prerequisites are TODOs** (replication slot `dr_slot`, `replicator`
role, `pg_hba` replication line, `max_wal_senders`) — see `dr/README.md`. True
multi-AZ + real RPO/RTO numbers need a real multi-zone deployment; this delivers
the mechanics + a local rehearsable drill.

## Run: KEDA lag-scaled consumers (H19.1.5)

Kubernetes, not compose — needs a local cluster + KEDA:

```bash
kind create cluster --name worldview
helm repo add kedacore https://kedacore.github.io/charts && helm repo update
helm install keda kedacore/keda --namespace keda --create-namespace --version 2.14.0
kubectl apply -k deploy/k8s/
kubectl -n worldview get deploy,scaledobject,hpa
```

Scales `live-writer` / `history-writer` / `recon-writer` on their Kafka consumer-group lag.
Needs a real in-cluster Redpanda broker + a real consumer image (both flagged TODO). See
`k8s/README.md`.

Run both add-on compose stacks together if you want:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/docker-compose.observability.yml \
  -f deploy/tiles/docker-compose.tiles.yml up -d
```

## Wiring the app

### 1. OTLP export (backend-api + ingestion-workers) — APP-SIDE FOLLOW-UP
Set on the app containers so traces/metrics/logs flow to the collector:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318   # HTTP (or :4317 for gRPC)
OTEL_SERVICE_NAME=worldview-api                           # per service
```

Then add the OTel SDK to each service (Node: `@opentelemetry/sdk-node` +
`@opentelemetry/exporter-*-otlp-http`; Python workers: `opentelemetry-sdk` + OTLP exporter).
This is the only code change required for traces/logs.

### 2. Prometheus `/metrics` scrape (backend-api) — APP-SIDE FOLLOW-UP
Prometheus is already configured to scrape `api:4000/metrics`. The API does **not** expose
that endpoint yet. Small follow-up: add a `prom-client` / `@fastify/metrics` registry on
`GET /metrics`. Expected metric names (the dashboards + alert rules assume these):

| Metric | Type | Used by |
| --- | --- | --- |
| `http_server_requests_total{http_route,http_response_status_code}` | counter | API throughput + error rate |
| `http_server_request_duration_seconds_bucket{http_route,le}` | histogram | API latency p50/p95/p99 |
| `worldview_ws_active_connections` | gauge | Live WS dashboard + alarm |
| `worldview_ws_messages_sent_total` | counter | Live WS throughput |
| `worldview_history_rows_written_total{domain}` | counter | Ingestion dashboard |

If you emit different names, update `observability/alerts.yml` and the dashboard JSON
together. **No app change is needed for the consumer-lag alarm or the ingestion lag panels** —
those come from Redpanda's own `:9644` metrics.

### 3. Tile URL (frontend) — config only
```
VITE_TILE_URL=http://localhost:3002/{table}/{z}/{x}/{y}.png
```
The map client substitutes `{table}` per layer (`adsb_positions`, `ais_positions`).

**Raster templates only.** The globe draws these as a Cesium imagery overlay, and Cesium's
imagery pipeline has no Mapbox-Vector-Tile decoder. A `.pbf`/`.mvt` template is refused by
`src/lib/tiles.ts` and the globe keeps rendering per-point marks — correct, but it means the
zoomed-out aggregation never kicks in. Serve raster tiles (or put a raster renderer in front of
Martin) for the 1M-point acceptance criterion.

## Optional: Redis metrics
Uncomment the `redis-exporter` service in `observability/docker-compose.observability.yml`
to light up the Redis panels (enables the `redis` scrape job already in `prometheus.yml`).

## Image pins

| Image | Tag |
| --- | --- |
| otel/opentelemetry-collector-contrib | 0.103.1 |
| prom/prometheus | v2.53.1 |
| grafana/grafana | 11.1.3 |
| ghcr.io/maplibre/martin | v0.14.2 |
| oliver006/redis_exporter (optional) | v1.62.0-alpine |
