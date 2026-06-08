// Prometheus metrics registry (ticket H19.5.5, app-side). Defines the five metrics the already-
// delivered observability stack (worldview/deploy/observability/) scrapes by EXACT name. The label
// names match what the shipped Grafana dashboards + alert rules actually query — OpenTelemetry-style
// `http_*` semantic-convention labels (`http_method`, `http_route`, `http_response_status_code`) and a
// `domain` label on the history counter — so /metrics lines up with prometheus.yml/alerts.yml without
// any dashboard edits.
//
// We use prom-client (the standard, lightweight Prometheus client) on a DEDICATED Registry (not the
// global default) so importing this module has no global side effects and tests stay isolated.
import { Counter, Gauge, Histogram, Registry } from "prom-client";

// A private registry — intentionally NOT the prom-client default registry, so we don't accidentally
// emit unrelated default/global metrics and tests don't bleed state through a shared singleton.
export const registry = new Registry();

// Histogram buckets tuned for web request latency: 5ms .. 10s. Covers fast in-memory routes up to
// slow DB-backed history queries while keeping bucket cardinality bounded.
export const HTTP_DURATION_BUCKETS = [
  0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10,
];

// http_server_requests_total — request count by method, matched-route pattern, and status code.
// Labels mirror the dashboard queries: http_method / http_route / http_response_status_code.
export const httpRequestsTotal = new Counter({
  name: "http_server_requests_total",
  help: "Total HTTP requests handled, by method, matched route, and response status code.",
  labelNames: ["http_method", "http_route", "http_response_status_code"] as const,
  registers: [registry],
});

// http_server_request_duration_seconds — request latency histogram by method + matched route.
// prom-client emits the _bucket/_sum/_count series Prometheus expects.
export const httpRequestDuration = new Histogram({
  name: "http_server_request_duration_seconds",
  help: "HTTP request duration in seconds, by method and matched route.",
  labelNames: ["http_method", "http_route"] as const,
  buckets: HTTP_DURATION_BUCKETS,
  registers: [registry],
});

// worldview_ws_active_connections — current count of open /live WebSocket connections.
export const wsActiveConnections = new Gauge({
  name: "worldview_ws_active_connections",
  help: "Currently open /live WebSocket connections.",
  registers: [registry],
});

// worldview_ws_messages_sent_total — total messages delivered to /live WS clients (snapshots + deltas).
export const wsMessagesSentTotal = new Counter({
  name: "worldview_ws_messages_sent_total",
  help: "Total messages delivered to /live WebSocket clients.",
  registers: [registry],
});

// worldview_history_rows_written_total — rows persisted to TimescaleDB by the history-writer, by domain.
export const historyRowsWrittenTotal = new Counter({
  name: "worldview_history_rows_written_total",
  help: "Total history rows written to TimescaleDB, by domain.",
  labelNames: ["domain"] as const,
  registers: [registry],
});

/** Prometheus text exposition of the registry. */
export async function renderMetrics(): Promise<string> {
  return registry.metrics();
}

/** The Content-Type the /metrics route must advertise. */
export const metricsContentType = registry.contentType;
