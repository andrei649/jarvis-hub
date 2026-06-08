import test from "node:test";
import assert from "node:assert/strict";
import Fastify from "fastify";
import {
  registry,
  renderMetrics,
  metricsContentType,
  httpRequestsTotal,
  httpRequestDuration,
  wsActiveConnections,
  wsMessagesSentTotal,
  historyRowsWrittenTotal,
} from "../src/metrics/registry.js";
import { metricsRoutes } from "../src/routes/metrics.js";
import { writeBatch, type Envelope } from "../src/repositories/historyWriter.js";
import { initTracing, shutdownTracing } from "../src/otel.js";

// Tests for the observability app-side (ticket H19.5.5): the registry serializes the five exact metric
// names the deploy/observability stack scrapes, the counters/histogram increment, the HTTP hook records
// a request with low-cardinality labels, the ws/history counters increment, and OTLP init is a strict
// no-op without the env var.

test("registry exposes the five expected metric names in Prometheus text format", async () => {
  const text = await renderMetrics();
  assert.match(text, /# TYPE http_server_requests_total counter/);
  assert.match(text, /# TYPE http_server_request_duration_seconds histogram/);
  assert.match(text, /# TYPE worldview_ws_active_connections gauge/);
  assert.match(text, /# TYPE worldview_ws_messages_sent_total counter/);
  assert.match(text, /# TYPE worldview_history_rows_written_total counter/);
  // Content type is the prom-client exposition format.
  assert.match(metricsContentType, /text\/plain/);
});

test("http duration histogram emits _bucket/_sum/_count series with method+route labels", async () => {
  httpRequestDuration.observe({ http_method: "GET", http_route: "/__t/dur" }, 0.05);
  const text = await renderMetrics();
  assert.match(
    text,
    /http_server_request_duration_seconds_bucket\{le="0\.1",http_method="GET",http_route="\/__t\/dur"\}/,
  );
  assert.match(text, /http_server_request_duration_seconds_sum\{http_method="GET",http_route="\/__t\/dur"\}/);
  assert.match(text, /http_server_request_duration_seconds_count\{http_method="GET",http_route="\/__t\/dur"\}/);
});

test("requests counter increments with method/route/status labels", async () => {
  httpRequestsTotal.inc({ http_method: "GET", http_route: "/__t/c", http_response_status_code: "200" });
  httpRequestsTotal.inc({ http_method: "GET", http_route: "/__t/c", http_response_status_code: "200" });
  const v = await registry.getSingleMetric("http_server_requests_total")!.get();
  const sample = v.values.find(
    (s) =>
      s.labels.http_route === "/__t/c" &&
      s.labels.http_method === "GET" &&
      s.labels.http_response_status_code === "200",
  );
  assert.ok(sample);
  assert.equal(sample!.value, 2);
});

test("ws gauge inc/dec and messages counter increment", async () => {
  const g0 = (await registry.getSingleMetric("worldview_ws_active_connections")!.get()).values[0]!.value;
  wsActiveConnections.inc();
  wsActiveConnections.inc();
  wsActiveConnections.dec();
  const g1 = (await registry.getSingleMetric("worldview_ws_active_connections")!.get()).values[0]!.value;
  assert.equal(g1 - g0, 1);

  const m0 = (await registry.getSingleMetric("worldview_ws_messages_sent_total")!.get()).values[0]!.value;
  wsMessagesSentTotal.inc();
  const m1 = (await registry.getSingleMetric("worldview_ws_messages_sent_total")!.get()).values[0]!.value;
  assert.equal(m1 - m0, 1);
});

test("history counter increments by inserted batch size, labeled by domain", async () => {
  // Fake pool: report rowCount === batch size so writeBatch increments by the batch length.
  const fakePool = {
    query: async (_sql: string, params: unknown[]) => ({ rowCount: params.length / 14 }),
  } as unknown as import("pg").Pool;
  const env: Envelope = {
    domain: "adsb",
    source: "s",
    entity_id: "abc",
    ts: 1,
    lon: 0,
    lat: 0,
    alt_m: null,
  };
  const written = await writeBatch(fakePool, "adsb", [env, env, env]);
  assert.equal(written, 3);
  const v = await registry.getSingleMetric("worldview_history_rows_written_total")!.get();
  const sample = v.values.find((s) => s.labels.domain === "adsb");
  assert.ok(sample);
  assert.ok(sample!.value >= 3);
});

test("HTTP hook records a request observed via GET /metrics (low-cardinality matched route)", async () => {
  // Minimal app mirroring server.ts's onRequest/onResponse instrumentation + the /metrics route and a
  // parameterized route. Asserts the matched-route PATTERN (not the raw URL) becomes the label.
  const app = Fastify();
  const REQ_START = Symbol("metricsStart");
  app.addHook("onRequest", async (req) => {
    (req as unknown as Record<symbol, number>)[REQ_START] = performance.now();
  });
  app.addHook("onResponse", async (req, reply) => {
    const route = req.routeOptions?.url;
    if (route === "/metrics") return;
    const http_route = route ?? "unmatched";
    httpRequestsTotal.inc({
      http_method: req.method,
      http_route,
      http_response_status_code: String(reply.statusCode),
    });
    const start = (req as unknown as Record<symbol, number>)[REQ_START];
    if (typeof start === "number") {
      httpRequestDuration.observe(
        { http_method: req.method, http_route },
        (performance.now() - start) / 1000,
      );
    }
  });
  app.get("/widgets/:id", async () => ({ ok: true }));
  await app.register(metricsRoutes);

  // Two requests with DIFFERENT path params must collapse to ONE route label series.
  await app.inject({ method: "GET", url: "/widgets/1" });
  await app.inject({ method: "GET", url: "/widgets/2" });

  const res = await app.inject({ method: "GET", url: "/metrics" });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] as string, /text\/plain/);
  // The matched-route pattern is the label, raw ids never appear.
  assert.match(
    res.body,
    /http_server_requests_total\{http_method="GET",http_route="\/widgets\/:id",http_response_status_code="200"\} 2/,
  );
  assert.doesNotMatch(res.body, /http_route="\/widgets\/1"/);
  // /metrics excluded from its own counter.
  assert.doesNotMatch(res.body, /http_route="\/metrics"/);
  await app.close();
});

test("OTLP init is a strict no-op without OTEL_EXPORTER_OTLP_ENDPOINT (no throw, no network)", async () => {
  const prev = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  delete process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  try {
    const started = await initTracing();
    assert.equal(started, false);
    await shutdownTracing(); // safe to call when disabled
  } finally {
    if (prev !== undefined) process.env.OTEL_EXPORTER_OTLP_ENDPOINT = prev;
  }
});
