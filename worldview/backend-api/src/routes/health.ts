import type { FastifyInstance } from "fastify";

// Liveness + readiness. STEP 4 extends readiness to ping Redis + TimescaleDB.
export async function healthRoutes(app: FastifyInstance) {
  app.get("/health", async () => ({ status: "ok", service: "worldview-api" }));
}
