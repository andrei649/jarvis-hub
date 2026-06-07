import Fastify from "fastify";
import cors from "@fastify/cors";
import websocket from "@fastify/websocket";
import { config } from "./config.js";
import { healthRoutes } from "./routes/health.js";
import { historyRoutes } from "./routes/history.js";
import { liveRoutes } from "./routes/live.js";
import { reconRoutes } from "./routes/recon.js";
import { startLiveWriter } from "./consumers/liveWriter.js";
import { startHistoryWriter } from "./consumers/historyWriter.js";
import { getRedis } from "./plugins/redis.js";
import { getPool } from "./plugins/db.js";

// The 4D API: REST `/history/:layer` serves as-of-T state from TimescaleDB; the `/live`
// WebSocket serves the Redis snapshot + pub/sub deltas. The Kafka->Redis live-writer runs
// alongside when ENABLE_LIVE_WRITER=1.

export async function buildServer() {
  const app = Fastify({ logger: true });

  await app.register(cors, { origin: config.corsOrigin });
  await app.register(websocket);
  await app.register(healthRoutes);
  await app.register(historyRoutes);
  await app.register(reconRoutes);
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
