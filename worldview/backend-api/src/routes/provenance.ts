import type { FastifyInstance } from "fastify";
import { getPool } from "../plugins/db.js";
import { isProvenanceLayer, provenanceOf } from "../repositories/provenance.js";

// Provenance / chain-of-custody API (ticket H19.4.3). Surfaces where a datum came from and the
// bitemporal pair behind it: valid time (`ts`, when it was true) vs transaction time
// (`ingested_at`, when WorldView recorded it). The per-feature provenance lives in the
// GeoJSON `properties` of every /history feature; this endpoint resolves the lineage of a single
// entity's last-known datum at/<=T. Times are UNIX seconds throughout.

interface ProvenanceParams {
  layer: string;
  entityId: string;
}
interface ProvenanceQuery {
  t?: string;
}

export async function provenanceRoutes(app: FastifyInstance): Promise<void> {
  // GET /provenance/:layer/:entityId?t=<unix-seconds>
  // Chain-of-custody of the entity's last-known datum at or before T (defaults to now).
  app.get<{ Params: ProvenanceParams; Querystring: ProvenanceQuery }>(
    "/provenance/:layer/:entityId",
    async (req, reply) => {
      const { layer, entityId } = req.params;
      if (!isProvenanceLayer(layer)) {
        return reply.code(404).send({ error: `no provenance for layer '${layer}'` });
      }
      const t = req.query.t ? Number(req.query.t) : Date.now() / 1000;
      if (Number.isNaN(t)) {
        return reply.code(400).send({ error: "query param 't' must be unix seconds" });
      }
      const provenance = await provenanceOf(getPool(), layer, entityId, t);
      if (!provenance) {
        return reply.code(404).send({ error: "no datum for this entity at/before t", provenance: null });
      }
      return reply.send({ provenance });
    },
  );
}
