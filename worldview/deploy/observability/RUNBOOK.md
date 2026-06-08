# WorldView Golden-Signal Runbook (H19.5.5)

This stack gives you the four golden signals (latency, traffic, errors, saturation)
across the WorldView pipeline: **API**, **ingestion/streaming**, and the **live WS path**.

## Bring the stack up

```bash
cd worldview
# infra (Redpanda + TimescaleDB + Redis) must be running first:
docker compose up -d
# add the observability stack on the same network:
docker compose -f docker-compose.yml -f deploy/observability/docker-compose.observability.yml up -d
```

Then open:

| What | URL | Login |
| --- | --- | --- |
| **Grafana** | http://localhost:3001 | admin / admin |
| Prometheus (targets/alerts) | http://localhost:9090 | — |
| OTel collector health | http://localhost:13133 | — |

Dashboards land in the **WorldView** folder in Grafana (auto-provisioned).
Check scrape health at Prometheus → Status → Targets, and alarms at Alerts.

Tear down (keep data volumes): `docker compose -f docker-compose.yml -f deploy/observability/docker-compose.observability.yml down`

## The dashboards

1. **API Golden Signals** (`worldview-api-golden`)
   - Request throughput (req/s per route), error rate (% 5xx), latency p50/p95/p99,
     availability (scrape `up`), requests by status class.
   - Healthy: error ratio ~0, p95 well under 1s, `up == 1`.

2. **Ingestion & Consumer Lag** (`worldview-ingestion-lag`)
   - Consumer-group lag per group (`live-writer` / `history-writer` / `recon-writer`),
     max lag stat, consume vs produce throughput per topic, history rows written/s.
   - Healthy: lag flat/near-zero; consume rate ≈ produce rate.

3. **Live / WebSocket Path** (`worldview-live-ws`)
   - Active WS connections, messages pushed/s, Redis pub/sub ops + connected clients
     (Redis panels need the optional `redis-exporter` sidecar).
   - Healthy: connections > 0 when clients are on the map, msgs/s tracks live traffic.

## The alarms (Prometheus → Alerts; rules in `alerts.yml`)

| Alert | Means | Threshold |
| --- | --- | --- |
| **KafkaConsumerLagHigh** | a consumer group is falling behind the firehose | lag > 50k for 5m (warning) |
| **KafkaConsumerLagCritical** | live map is going stale | lag > 250k for 10m (critical) |
| **ApiErrorRateHigh** | API is throwing 5xx | >5% 5xx for 5m (critical) |
| **ApiLatencyHigh** | API is slow | p95 > 1s for 5m (warning) |
| **ApiDown** | API /metrics unscrapable | `up{job="backend-api"}==0` for 2m |
| **LiveWsConnectionsDropped** | WS fan-out broke | ws conns == 0 while API up, 5m |

## First-response playbooks

### #consumer-lag — lag alarm fired
1. **Dashboard:** open *Ingestion & Consumer Lag*; identify which group is lagging.
2. **Is it producing faster than consuming?** Compare produce vs consume throughput.
   If produce spiked (real-world event), this may be transient — watch it drain.
3. **Worker health:** `docker compose logs -f api` (the writers run inside the API with
   `ENABLE_LIVE_WRITER` / `ENABLE_HISTORY_WRITER`). Crash-looping or DB-blocked writer
   keeps lag climbing.
4. **Scale the consumer group:** run more API replicas (the writers are a Kafka consumer
   group; adding members splits partitions). ADS-B is the heaviest stream.
5. **DB back-pressure:** if `history-writer` lags, check TimescaleDB — slow inserts,
   compression jobs, or disk. The writer is idempotent (`ON CONFLICT DO NOTHING`), so
   it is safe to restart / replay from the last committed offset.
6. **Replay:** since consumers commit offsets, restarting resumes where they left off;
   no data loss for at-least-once delivery.

### #api-errors — 5xx rate high
1. **Logs first:** `docker compose logs -f api` — look for stack traces / dependency errors.
2. **DB:** `docker compose exec timescaledb pg_isready -U worldview -d worldview`; check
   connection-pool exhaustion and slow `/history` queries.
3. **Redis:** `docker compose exec redis redis-cli ping` — live reads hit Redis.
4. **Correlate:** if errors align with a lag spike, the root cause is likely downstream
   (DB/Redis), not the API itself.

### #api-latency — p95 high
1. Check the latency panel split by route — is it `/history` (DB-bound) or `/live`?
2. DB: long-range/zoomed-out queries should use the `lod=minute` continuous-aggregate
   path, not the raw hypertable. Check query plans.
3. CPU/memory on the host — local laptop runs are easily CPU-bound.

### #ws-path — WS connections dropped to zero
1. Confirm clients are actually connected (open the dashboard in a browser tab).
2. **Redis is the fan-out bus:** `docker compose exec redis redis-cli ping` and
   `redis-cli pubsub channels` — the live-writer publishes, the WS layer subscribes.
   If Redis is down or pub/sub is silent, the live path is broken even if the API is up.
3. Check the API `/live` endpoint and `ENABLE_LIVE_WRITER=1` on the API.

## Notes / known gaps

- **`backend-api:4000/metrics` and the OTLP exporter are not wired in the app yet** —
  see the app-side follow-up in `deploy/README.md`. Until then, `ApiDown` will fire and
  the API/live dashboards stay empty; the **ingestion lag** dashboard + alarm work from
  Redpanda's own `:9644` metrics with no app change.
- Redis panels need the optional `redis-exporter` sidecar (commented in the compose file).
- SLO thresholds here (50k lag, 5% errors, 1s p95) are laptop-sane defaults; tune per
  environment. At-scale SLO numbers require real hardware.
