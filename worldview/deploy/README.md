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

Run both add-on stacks together if you want:

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
NEXT_PUBLIC_TILE_URL=http://localhost:3002/{table}/{z}/{x}/{y}
```
The map client substitutes `{table}` per layer (`adsb_positions`, `ais_positions`).

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
