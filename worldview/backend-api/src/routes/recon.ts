import type { FastifyInstance, FastifyRequest } from "fastify";
import { getPool } from "../plugins/db.js";
import { dueAlerts, upcomingWindows } from "../repositories/recon.js";
import { inScope, type Principal } from "../auth/rbac.js";

// Resolve the request principal for ABAC AOI scoping. The guard decorates `request.principal` on every
// request; when the recon plugin is mounted WITHOUT the guard (e.g. unit tests register the route in
// isolation) `principal` is absent — treat that as unrestricted so back-compat behavior is preserved.
function principalOf(req: FastifyRequest): Principal | null {
  const p = (req as FastifyRequest & { principal?: Principal }).principal;
  return p ?? null;
}

// Recon-window API (ticket H19.2.2): list upcoming predicted satellite overflights of an AOI,
// and the subset that's due to ingress within a lead time (the alertable set). Times are
// UNIX seconds throughout.

const DEFAULT_WINDOW_SECONDS = 24 * 3600; // /recon/windows default: now -> now+24h
const DEFAULT_LEAD_SECONDS = 900; // /recon/alerts default: ingressing within 15 min

interface WindowsQuery {
  aoi?: string;
  from?: string;
  to?: string;
}
interface AlertsQuery {
  lead?: string;
}

export async function reconRoutes(app: FastifyInstance): Promise<void> {
  // GET /recon/windows?aoi=<id>&from=<unix>&to=<unix>
  // Upcoming windows in [from, to] (defaults to now -> now+24h), optionally filtered by AOI.
  app.get<{ Querystring: WindowsQuery }>("/recon/windows", async (req, reply) => {
    const now = Date.now() / 1000;
    const from = req.query.from ? Number(req.query.from) : now;
    const to = req.query.to ? Number(req.query.to) : from + DEFAULT_WINDOW_SECONDS;
    if (Number.isNaN(from) || Number.isNaN(to)) {
      return reply.code(400).send({ error: "'from'/'to' must be unix seconds" });
    }
    const aoiId = req.query.aoi || undefined;

    // ABAC AOI scoping: a non-admin principal whose token restricts `aois` may only see windows for
    // those AOIs. If the request asks for a specific `aoi` outside scope, deny (403); otherwise filter
    // the result set to the in-scope AOIs. admin / `aois=["*"]` (or no principal) bypass scoping.
    const principal = principalOf(req);
    if (principal && aoiId && !inScope(principal, aoiId)) {
      return reply.code(403).send({ error: "forbidden", reason: `AOI '${aoiId}' is out of scope` });
    }
    const windows = await upcomingWindows(getPool(), { aoiId, from, to });
    const scoped = principal
      ? windows.filter((w) => inScope(principal, w.aoi_id))
      : windows;
    return reply.send({ windows: scoped });
  });

  // GET /recon/alerts?lead=<seconds>
  // Windows ingressing within `lead` seconds of now (default 900s).
  app.get<{ Querystring: AlertsQuery }>("/recon/alerts", async (req, reply) => {
    const leadSeconds = req.query.lead ? Number(req.query.lead) : DEFAULT_LEAD_SECONDS;
    if (Number.isNaN(leadSeconds)) {
      return reply.code(400).send({ error: "'lead' must be a number of seconds" });
    }
    const now = Date.now() / 1000;
    const alerts = await dueAlerts(getPool(), { now, leadSeconds });
    return reply.send({ alerts });
  });
}
