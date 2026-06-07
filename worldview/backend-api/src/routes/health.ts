import type { FastifyInstance } from "fastify";
import { getPool } from "../plugins/db.js";
import { getRedis } from "../plugins/redis.js";

// Liveness (/health) is dependency-free; readiness (/ready) pings Redis + TimescaleDB.
export async function healthRoutes(app: FastifyInstance): Promise<void> {
  app.get("/health", async () => ({ status: "ok", service: "worldview-api" }));

  app.get("/ready", async (_req, reply) => {
    const checks: Record<string, boolean> = { db: false, redis: false };
    try {
      await getPool().query("SELECT 1");
      checks.db = true;
    } catch {
      checks.db = false;
    }
    try {
      await getRedis().ping();
      checks.redis = true;
    } catch {
      checks.redis = false;
    }
    const ready = checks.db && checks.redis;
    return reply.code(ready ? 200 : 503).send({ ready, checks });
  });
}
