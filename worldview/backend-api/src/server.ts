import Fastify, { type FastifyReply, type FastifyRequest } from "fastify";
import cors from "@fastify/cors";
import websocket from "@fastify/websocket";
import { config } from "./config.js";
import { initTracing, shutdownTracing } from "./otel.js";
import { httpRequestDuration, httpRequestsTotal } from "./metrics/registry.js";
import { healthRoutes } from "./routes/health.js";
import { metricsRoutes } from "./routes/metrics.js";
import { historyRoutes } from "./routes/history.js";
import { liveRoutes } from "./routes/live.js";
import { ontologyRoutes } from "./routes/ontology.js";
import { caseRoutes } from "./routes/cases.js";
import { reconstructionRoutes } from "./routes/reconstruction.js";
import { provenanceRoutes } from "./routes/provenance.js";
import { reconRoutes } from "./routes/recon.js";
import { startLiveWriter } from "./consumers/liveWriter.js";
import { startHistoryWriter } from "./consumers/historyWriter.js";
import { startReconWriter } from "./consumers/reconWriter.js";
import { getRedis } from "./plugins/redis.js";
import { getPool } from "./plugins/db.js";
import { registerGuard } from "./auth/guard.js";

// The 4D API: REST `/history/:layer` serves as-of-T state from TimescaleDB; the `/live`
// WebSocket serves the Redis snapshot + pub/sub deltas. The Kafka->Redis live-writer runs
// alongside when ENABLE_LIVE_WRITER=1.

// Per-request start time for latency measurement. Stashed on the request object behind a symbol so it
// never collides with Fastify/plugin properties and needs no `declare module` augmentation.
const REQ_START = Symbol("metricsStart");

// Record an HTTP request into the Prometheus metrics. Uses the LOW-CARDINALITY matched-route pattern
// (request.routeOptions.url, e.g. "/history/:layer") — NOT the raw URL — so path params and query
// strings never explode label cardinality. Unmatched requests (404s) collapse to "unmatched" for the
// same reason. The whole body is exception-safe: instrumentation must never throw into the response.
function recordHttp(req: FastifyRequest, reply: FastifyReply): void {
  try {
    const route = req.routeOptions?.url;
    // Skip the /metrics scrape itself so it doesn't inflate its own counters.
    if (route === "/metrics") return;

    const http_route = route ?? "unmatched";
    const http_method = req.method;
    const http_response_status_code = String(reply.statusCode);
    httpRequestsTotal.inc({ http_method, http_route, http_response_status_code });

    const start = (req as unknown as Record<symbol, number>)[REQ_START];
    if (typeof start === "number") {
      httpRequestDuration.observe(
        { http_method, http_route },
        (performance.now() - start) / 1000,
      );
    }
  } catch {
    // Never let metrics break the response path.
  }
}

export async function buildServer() {
  const app = Fastify({ logger: true });

  // HTTP instrumentation (ticket H19.5.5): time on onRequest, record on onResponse. Registered before
  // the routes/guard so it wraps every request. Both hooks are exception-safe.
  app.addHook("onRequest", async (req: FastifyRequest) => {
    try {
      (req as unknown as Record<symbol, number>)[REQ_START] = performance.now();
    } catch {
      // ignore — duration will simply be skipped for this request
    }
  });
  app.addHook("onResponse", async (req: FastifyRequest, reply: FastifyReply) => {
    recordHttp(req, reply);
  });

  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocket);
  // AuthN/Z guard (ticket H19.4.2): registered BEFORE the routes so its onRequest hook + the
  // `request.principal` decorator are in place for every handler. No-op when WORLDVIEW_AUTH_SECRET
  // is unset (open mode); fail-CLOSED RBAC + AOI scoping when set.
  await registerGuard(app);
  await app.register(healthRoutes);
  await app.register(metricsRoutes);
  await app.register(historyRoutes);
  await app.register(reconRoutes);
  await app.register(provenanceRoutes);
  await app.register(ontologyRoutes);
  await app.register(caseRoutes);
  await app.register(reconstructionRoutes);
  await app.register(liveRoutes);

  if (config.enableLiveWriter) {
    const consumer = await startLiveWriter(getRedis(), config.kafkaBrokers);
    app.addHook("onClose", async () => {
      await consumer.disconnect();
    });
  }

  if (config.enableHistoryWriter) {
    const consumer = await startHistoryWriter(getPool(), config.kafkaBrokers);
    app.addHook("onClose", async () => {
      await consumer.stop();
      await consumer.disconnect();
    });
  }

  if (config.enableReconWriter) {
    const consumer = await startReconWriter(getPool(), config.kafkaBrokers);
    app.addHook("onClose", async () => {
      await consumer.stop();
      await consumer.disconnect();
    });
  }

  return app;
}

async function main() {
  // Initialize OTLP tracing FIRST (before the app/instrumentations load) — strictly opt-in and no-op
  // unless OTEL_EXPORTER_OTLP_ENDPOINT is set, so this is safe to call unconditionally.
  await initTracing();
  const app = await buildServer();
  app.addHook("onClose", async () => {
    await shutdownTracing();
  });
  try {
    await app.listen({ port: config.port, host: config.host });
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }
}

// Only auto-start when run directly (so tests can import buildServer()).
if (import.meta.url === `file://${process.argv[1]}`) {
  void main();
}
