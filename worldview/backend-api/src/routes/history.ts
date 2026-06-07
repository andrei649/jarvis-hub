import type { FastifyInstance } from "fastify";
import { getPool } from "../plugins/db.js";
import { HISTORY_BY_LAYER, TRACK_LAYERS, trackOf } from "../repositories/history.js";
import { isLayer, parseBBox } from "../types.js";

interface HistoryParams {
  layer: string;
}
interface HistoryQuery {
  t?: string;
  bbox?: string;
}
interface TrackParams {
  layer: string;
  entityId: string;
}
interface TrackQuery {
  from?: string;
  to?: string;
}

// GET /history/:layer?t=<unix-seconds>&bbox=w,s,e,n
// Returns the as-of-T reconstruction for one layer as a GeoJSON FeatureCollection.
export async function historyRoutes(app: FastifyInstance): Promise<void> {
  app.get<{ Params: HistoryParams; Querystring: HistoryQuery }>(
    "/history/:layer",
    async (req, reply) => {
      const { layer } = req.params;
      if (!isLayer(layer)) {
        return reply.code(404).send({ error: `unknown layer '${layer}'` });
      }
      const t = Number(req.query.t);
      if (!req.query.t || Number.isNaN(t)) {
        return reply.code(400).send({ error: "query param 't' (unix seconds) is required" });
      }
      const bbox = parseBBox(req.query.bbox);
      const fc = await HISTORY_BY_LAYER[layer](getPool(), t, bbox);
      return reply.send(fc);
    },
  );

  // GET /history/:layer/:entityId/track?from=<unix>&to=<unix>
  // One entity's trail as a GeoJSON LineString (defaults to the trailing hour).
  app.get<{ Params: TrackParams; Querystring: TrackQuery }>(
    "/history/:layer/:entityId/track",
    async (req, reply) => {
      const { layer, entityId } = req.params;
      if (!TRACK_LAYERS.includes(layer)) {
        return reply.code(404).send({ error: `no track available for layer '${layer}'` });
      }
      const to = req.query.to ? Number(req.query.to) : Date.now() / 1000;
      const from = req.query.from ? Number(req.query.from) : to - 3600;
      if (Number.isNaN(from) || Number.isNaN(to)) {
        return reply.code(400).send({ error: "'from'/'to' must be unix seconds" });
      }
      const fc = await trackOf(getPool(), layer, entityId, from, to);
      return reply.send(fc);
    },
  );
}
