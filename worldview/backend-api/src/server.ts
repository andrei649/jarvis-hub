import Fastify from "fastify";
import cors from "@fastify/cors";
import websocket from "@fastify/websocket";
import { config } from "./config.js";
import { healthRoutes } from "./routes/health.js";

// STEP 2 scaffold: the Fastify bootstrap with a /health route and the WebSocket plugin
// registered. The REST history endpoints (TimescaleDB as-of-T) and the /live WebSocket
// telemetry stream (Redis snapshot + pub/sub deltas) are implemented in STEP 4.

export async function buildServer() {
  const app = Fastify({ logger: true });

  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocket);
  await app.register(healthRoutes);

  return app;
}

async function main() {
  const app = await buildServer();
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
