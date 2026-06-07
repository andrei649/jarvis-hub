import type { FastifyInstance, FastifyRequest } from "fastify";
import type { WebSocket } from "@fastify/websocket";
import { getRedis } from "../plugins/redis.js";
import { channel, liveSnapshot } from "../repositories/live.js";
import { isLayer, LAYERS, parseBBox, pointInBBox, type BBox, type Layer } from "../types.js";

interface LiveQuery {
  layers?: string;
}

// WebSocket /live?layers=adsb,ais
// On connect: send one snapshot per requested layer from Redis, then stream deltas as the
// live-writer publishes them on chan:<layer>. The client advances its master clock in realtime.
export async function liveRoutes(app: FastifyInstance): Promise<void> {
  app.get<{ Querystring: LiveQuery }>(
    "/live",
    { websocket: true },
    (socket: WebSocket, req: FastifyRequest<{ Querystring: LiveQuery }>) => {
      const layers = resolveLayers(req.query.layers);
      const redis = getRedis();

      // Per-connection viewport: when set, only deltas inside it are forwarded (the client
      // sends `{type:"viewport", bbox:"w,s,e,n"}` as it pans/zooms). Null = stream everything.
      let viewport: BBox | null = null;
      socket.on("message", (raw: Buffer | string) => {
        try {
          const msg = JSON.parse(raw.toString()) as { type?: string; bbox?: string };
          if (msg.type === "viewport") viewport = parseBBox(msg.bbox);
        } catch {
          // ignore malformed client messages
        }
      });

      // Initial snapshot per layer.
      for (const layer of layers) {
        liveSnapshot(redis, layer)
          .then((data) => socket.send(JSON.stringify({ type: "snapshot", layer, data })))
          .catch((err) => req.log.warn({ err }, "snapshot failed"));
      }

      // Dedicated subscriber connection (ioredis subscribers can't issue other commands).
      const sub = redis.duplicate();
      void sub.subscribe(...layers.map(channel));
      sub.on("message", (chan, payload) => {
        const layer = chan.split(":")[1];
        const env = JSON.parse(payload) as { lon?: number | null; lat?: number | null };
        if (env.lon != null && env.lat != null && !pointInBBox(env.lon, env.lat, viewport)) {
          return; // outside the client's viewport — skip
        }
        socket.send(JSON.stringify({ type: "delta", layer, data: env }));
      });

      socket.on("close", () => {
        void sub.quit();
      });
    },
  );
}

function resolveLayers(raw: string | undefined): Layer[] {
  if (!raw) return [...LAYERS];
  const requested = raw.split(",").filter(isLayer);
  return requested.length > 0 ? requested : [...LAYERS];
}
