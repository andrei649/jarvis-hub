import type { FastifyInstance } from "fastify";
import { getPool } from "../plugins/db.js";
import { HISTORY_BY_LAYER } from "../repositories/history.js";
import { isLayer, parseBBox } from "../types.js";

interface HistoryParams {
  layer: string;
}
interface HistoryQuery {
  t?: string;
  bbox?: string;
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
}
