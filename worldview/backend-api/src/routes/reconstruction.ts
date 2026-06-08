import type { FastifyInstance, FastifyRequest } from "fastify";
import { getPool } from "../plugins/db.js";
import {
  createReconstruction,
  getReconstruction,
  listReconstructions,
} from "../repositories/reconstruction.js";
import {
  exportReconstruction,
  exportCase,
  type CaseFormat,
  type ReconstructionFormat,
} from "../repositories/export.js";
import type { Principal } from "../auth/rbac.js";

// Reconstruction + export API (tickets H19.2.7 "Event reconstruction + shareable replay export" and
// H19.4.6 "Export / reporting"). A saved RECONSTRUCTION is the shareable replay handle: POST it once,
// GET it / list it, and GET /reconstructions/:id/export?format=json|geojson to download a reproducible
// bundle (the frames are RE-DERIVED from the saved params on every export — never a frozen copy). The
// case export (GET /cases/:id/export?format=brief|geojson|json) bundles a case into a Markdown brief, a
// GeoJSON of its items, or the full structured JSON. Access is gated CENTRALLY by the auth guard against
// rbac.ts: export READS need read:export (viewer+); CREATING a reconstruction needs write:reconstruction
// (analyst+). Handlers here just resolve the acting identity + parse/guard the body/query.

interface IdParams {
  id: string;
}
interface ExportQuery {
  format?: string;
}

const RECONSTRUCTION_FORMATS: ReadonlySet<string> = new Set(["json", "geojson"]);
const CASE_FORMATS: ReadonlySet<string> = new Set(["json", "geojson", "brief"]);

// The acting identity: the authenticated principal's `sub` if present, else an `X-Actor` header, else
// null. Mirrors routes/cases.ts so every write records a consistent actor.
function actorOf(req: FastifyRequest): string | null {
  const principal = (req as FastifyRequest & { principal?: Principal }).principal;
  if (principal && principal.sub && principal.sub.trim()) return principal.sub.trim();
  const h = req.headers["x-actor"];
  if (typeof h === "string" && h.trim()) return h.trim();
  return null;
}

function parseId(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

// Guard body parsing: Fastify pre-parses JSON, but a non-object body would break field access — coerce
// to {} so handlers see a plain record (mirrors routes/cases.ts).
function bodyOf(body: unknown): Record<string, unknown> {
  if (body && typeof body === "object" && !Array.isArray(body)) {
    return body as Record<string, unknown>;
  }
  return {};
}

export async function reconstructionRoutes(app: FastifyInstance): Promise<void> {
  const pool = () => getPool();

  // POST /reconstructions — save a shareable reconstruction handle (audited reconstruction.create).
  // Body: { title?, from, to, stepSeconds, bbox?, layers[] }. Params are validated in the repository
  // (from<to, sane step/layers/bbox, within the frame cap); an invalid body is a 400.
  app.post("/reconstructions", async (req, reply) => {
    const body = bodyOf(req.body);
    const title = typeof body.title === "string" ? body.title : null;
    try {
      const created = await createReconstruction(pool(), {
        title,
        params: body,
        actor: actorOf(req),
      });
      return reply.code(201).send({ reconstruction: created });
    } catch (err) {
      // validateParams threw with a human-readable reason — surface as a 400.
      return reply.code(400).send({ error: (err as Error).message });
    }
  });

  // GET /reconstructions — list saved reconstructions, newest first.
  app.get("/reconstructions", async (_req, reply) => {
    const reconstructions = await listReconstructions(pool());
    return reply.send({ reconstructions });
  });

  // GET /reconstructions/:id — one saved reconstruction handle.
  app.get<{ Params: IdParams }>("/reconstructions/:id", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const found = await getReconstruction(pool(), id);
    if (!found) {
      return reply.code(404).send({ error: `no reconstruction with id '${req.params.id}'` });
    }
    return reply.send({ reconstruction: found });
  });

  // GET /reconstructions/:id/export?format=json|geojson — a self-contained, reproducible replay bundle
  // (frames re-derived from the saved params). Defaults to json.
  app.get<{ Params: IdParams; Querystring: ExportQuery }>(
    "/reconstructions/:id/export",
    async (req, reply) => {
      const id = parseId(req.params.id);
      if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
      const format = req.query.format ?? "json";
      if (!RECONSTRUCTION_FORMATS.has(format)) {
        return reply.code(400).send({ error: "'format' must be one of json|geojson" });
      }
      const result = await exportReconstruction(pool(), id, format as ReconstructionFormat);
      if (!result) {
        return reply.code(404).send({ error: `no reconstruction with id '${req.params.id}'` });
      }
      return reply.send(result.body);
    },
  );

  // GET /cases/:id/export?format=brief|geojson|json — a reproducible case bundle. `brief` is a Markdown
  // report (served as text/markdown), `geojson` the case items' geometries, `json` the full bundle.
  app.get<{ Params: IdParams; Querystring: ExportQuery }>(
    "/cases/:id/export",
    async (req, reply) => {
      const id = parseId(req.params.id);
      if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
      const format = req.query.format ?? "json";
      if (!CASE_FORMATS.has(format)) {
        return reply.code(400).send({ error: "'format' must be one of brief|geojson|json" });
      }
      const result = await exportCase(pool(), id, format as CaseFormat);
      if (!result) {
        return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
      }
      if (result.format === "brief") {
        const { markdown } = result.body as { markdown: string };
        return reply.type("text/markdown; charset=utf-8").send(markdown);
      }
      return reply.send(result.body);
    },
  );
}
