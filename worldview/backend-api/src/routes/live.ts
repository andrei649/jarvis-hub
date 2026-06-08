import type { FastifyInstance, FastifyRequest } from "fastify";
import type { WebSocket } from "@fastify/websocket";
import { getRedis } from "../plugins/redis.js";
import { liveSnapshot } from "../repositories/live.js";
import { config } from "../config.js";
import { Coalescer } from "../live/coalescer.js";
import { planSubscription } from "../live/subscription.js";
import { isLayer, LAYERS, parseBBox, pointInBBox, type BBox, type Layer } from "../types.js";

interface LiveQuery {
  layers?: string;
  // Connect-time viewport "w,s,e,n". When present (and geohash sharding is enabled) the client is
  // subscribed only to the geohash cells covering it; absent → global channels (back-compat).
  bbox?: string;
}

// A delta as it travels over the socket: the raw envelope plus the layer it belongs to. In geo
// mode the layer comes from the envelope's `domain`; in global mode from the channel name.
interface SocketDelta {
  layer: string;
  env: DeltaEnvelope;
}

interface DeltaEnvelope {
  domain?: string;
  entity_id?: string;
  lon?: number | null;
  lat?: number | null;
}

// WebSocket /live?layers=adsb,ais&bbox=w,s,e,n
// On connect: send one snapshot per requested layer from Redis, then stream deltas. Deltas are
// coalesced per-entity and flushed on an interval (WS_COALESCE_MS) so each client's outbound rate
// is bounded regardless of the upstream firehose. Channels are sharded by geohash so a client with
// a bbox only subscribes to (and receives) deltas for its viewport.
export async function liveRoutes(app: FastifyInstance): Promise<void> {
  app.get<{ Querystring: LiveQuery }>(
    "/live",
    { websocket: true },
    (socket: WebSocket, req: FastifyRequest<{ Querystring: LiveQuery }>) => {
      const layers = resolveLayers(req.query.layers);
      const layerSet = new Set<string>(layers);
      const redis = getRedis();

      // Per-connection viewport. Seeded from the connect-time `?bbox=` query param, and updated when
      // the client sends `{type:"viewport", bbox:"w,s,e,n"}` as it pans/zooms. Null = stream
      // everything in the subscribed channels.
      let viewport: BBox | null = parseBBox(req.query.bbox);

      // Plan the channel subscription from the connect-time viewport. We subscribe once at connect
      // time; a viewport message narrows the in-process filter but (per the protocol note) does not
      // re-subscribe — a client wanting a different cell set reconnects with a new ?bbox=.
      const plan = planSubscription(layers, viewport, config.wsGeohashPrecision);

      // Per-client coalescer: collapses repeated deltas for the same entity to the latest and
      // flushes batches, bounding the outbound message rate. When WS_COALESCE_MS<=0 we send
      // immediately (back-compat, no batching).
      const coalescing = config.wsCoalesceMs > 0;
      const coalescer = coalescing
        ? new Coalescer<SocketDelta>({
            keyOf: (d) => `${d.layer}:${d.env.entity_id ?? ""}`,
            intervalMs: config.wsCoalesceMs,
            maxBatch: config.wsCoalesceMaxBatch,
            maxQueue: config.wsMaxClientQueue,
            onFlush: (batch) => {
              if (socket.readyState !== socket.OPEN) return;
              for (const d of batch) {
                socket.send(JSON.stringify({ type: "delta", layer: d.layer, data: d.env }));
              }
            },
          })
        : null;
      coalescer?.start();

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
      void sub.subscribe(...plan.channels);
      sub.on("message", (chan, payload) => {
        // Poison-pill safe: a malformed payload on the pub/sub path must never crash the handler.
        let env: DeltaEnvelope;
        try {
          env = JSON.parse(payload) as DeltaEnvelope;
        } catch {
          return;
        }
        // Resolve the layer: geo channels (`live:geo:<cell>`) carry mixed layers, so read it from
        // the envelope's domain; global channels (`chan:<layer>`) encode it in the channel name.
        const layer = plan.mode === "geo" ? env.domain : chan.split(":")[1];
        if (!layer || !layerSet.has(layer)) return;

        // Viewport filter: in geo mode a cell may slightly overspill the bbox, and in global mode we
        // never sharded — either way only forward in-viewport points.
        if (env.lon != null && env.lat != null && !pointInBBox(env.lon, env.lat, viewport)) {
          return;
        }

        if (coalescer) {
          coalescer.push({ layer, env });
        } else if (socket.readyState === socket.OPEN) {
          socket.send(JSON.stringify({ type: "delta", layer, data: env }));
        }
      });

      socket.on("close", () => {
        coalescer?.close();
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
