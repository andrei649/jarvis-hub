import type { FastifyInstance } from "fastify";
import { metricsContentType, renderMetrics } from "../metrics/registry.js";

// GET /metrics — Prometheus text exposition (ticket H19.5.5). Kept PUBLIC (like /health and /ready,
// which have no auth rule) so the in-cluster Prometheus can scrape it without a bearer, matching the
// shipped prometheus.yml scrape config. The HTTP instrumentation hook in server.ts excludes this
// route from its own counters so scraping doesn't inflate request metrics.
export async function metricsRoutes(app: FastifyInstance): Promise<void> {
  app.get("/metrics", async (_req, reply) => {
    const body = await renderMetrics();
    return reply.header("content-type", metricsContentType).send(body);
  });
}
