import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { getPool } from "../plugins/db.js";
import {
  describeRegistry,
  getActionSpec,
  isAction,
  isObjectType,
} from "../ontology/registry.js";
import { getObject, linksOf, listObjects } from "../repositories/ontology.js";
import {
  listActions,
  recordAction,
  recordAnnotation,
  verifyAuditChain,
} from "../repositories/ontologyAudit.js";

// Ontology API (ticket H19.4.1) — the Palantir-style object/link/action surface over the relational
// SoR. Reads project Objects + Links from the existing tables; the one POST endpoint performs an
// AUDITED action (every invocation appends an ontology_actions row before returning). type/action are
// validated against the registry so unknown ones are rejected (404). Times are UNIX seconds.

interface TypeParams {
  type: string;
}
interface ObjectParams {
  type: string;
  id: string;
}
interface ActionParams {
  type: string;
  id: string;
  action: string;
}
interface ListQuery {
  limit?: string;
}
interface ActionsQuery {
  type?: string;
  id?: string;
  limit?: string;
}

// The audited actor is taken from a header (no auth layer yet); falls back to anonymous. Centralized
// so every action records a consistent actor.
function actorOf(req: FastifyRequest): string | null {
  const h = req.headers["x-actor"];
  if (typeof h === "string" && h.trim()) return h.trim();
  return null;
}

// Guard body parsing: Fastify pre-parses JSON, but a non-object body (array/string/null) would break
// the param-validate contract — coerce to {} so validators see a plain record.
function bodyParams(body: unknown): Record<string, unknown> {
  if (body && typeof body === "object" && !Array.isArray(body)) {
    return body as Record<string, unknown>;
  }
  return {};
}

export async function ontologyRoutes(app: FastifyInstance): Promise<void> {
  // GET /ontology/types → the registry: object types, link types, actions.
  app.get("/ontology/types", async (_req, reply) => {
    return reply.send(describeRegistry());
  });

  // GET /ontology/actions?type=&id=&limit= → the audit trail (so actions are verifiably audited).
  // Registered BEFORE the parameterized /ontology/objects/:type routes; distinct path, no conflict.
  app.get<{ Querystring: ActionsQuery }>("/ontology/actions", async (req, reply) => {
    const limit = req.query.limit ? Number(req.query.limit) : undefined;
    if (limit !== undefined && Number.isNaN(limit)) {
      return reply.code(400).send({ error: "'limit' must be a number" });
    }
    const actions = await listActions(getPool(), {
      objectType: req.query.type || undefined,
      objectId: req.query.id || undefined,
      limit,
    });
    return reply.send({ actions });
  });

  // GET /ontology/audit/verify?limit= → verify the tamper-evident hash chain (ticket H19.4.4).
  // Walks the audit log in id order, recomputing each row's entry_hash and checking the prev_hash
  // links, and returns { ok, count, brokenAtId?, reason? } pinpointing the FIRST broken link.
  // Registered before the parameterized /ontology/objects/:type routes; distinct path, no conflict.
  app.get<{ Querystring: ListQuery }>("/ontology/audit/verify", async (req, reply) => {
    const limit = req.query.limit ? Number(req.query.limit) : undefined;
    if (limit !== undefined && Number.isNaN(limit)) {
      return reply.code(400).send({ error: "'limit' must be a number" });
    }
    const result = await verifyAuditChain(getPool(), { limit });
    return reply.send(result);
  });

  // GET /ontology/objects/:type?limit= → list objects of a type (latest state).
  app.get<{ Params: TypeParams; Querystring: ListQuery }>(
    "/ontology/objects/:type",
    async (req, reply) => {
      const { type } = req.params;
      if (!isObjectType(type)) {
        return reply.code(404).send({ error: `unknown object type '${type}'` });
      }
      const limit = req.query.limit ? Number(req.query.limit) : undefined;
      if (limit !== undefined && Number.isNaN(limit)) {
        return reply.code(400).send({ error: "'limit' must be a number" });
      }
      const objects = await listObjects(getPool(), type, { limit });
      return reply.send({ type, objects });
    },
  );

  // GET /ontology/objects/:type/:id → one object.
  app.get<{ Params: ObjectParams }>(
    "/ontology/objects/:type/:id",
    async (req, reply) => {
      const { type, id } = req.params;
      if (!isObjectType(type)) {
        return reply.code(404).send({ error: `unknown object type '${type}'` });
      }
      const object = await getObject(getPool(), type, id);
      if (!object) {
        return reply.code(404).send({ error: `no ${type} object with id '${id}'` });
      }
      return reply.send({ object });
    },
  );

  // GET /ontology/objects/:type/:id/links → the object's outgoing links.
  app.get<{ Params: ObjectParams }>(
    "/ontology/objects/:type/:id/links",
    async (req, reply) => {
      const { type, id } = req.params;
      if (!isObjectType(type)) {
        return reply.code(404).send({ error: `unknown object type '${type}'` });
      }
      const links = await linksOf(getPool(), type, id);
      return reply.send({ type, id, links });
    },
  );

  // POST /ontology/objects/:type/:id/actions/:action → perform an AUDITED action.
  // Validates type + action against the registry, runs the action's effect, and ALWAYS appends an
  // audit row recording the invocation + its result.
  app.post<{ Params: ActionParams }>(
    "/ontology/objects/:type/:id/actions/:action",
    async (req, reply) => {
      return performAction(req, reply);
    },
  );
}

// The action handler: validate registry membership + params, perform the (small) effect, then write
// the audit row with the result. Split out so the logic is easy to test/extend per action.
async function performAction(
  req: FastifyRequest<{ Params: ActionParams }>,
  reply: FastifyReply,
): Promise<unknown> {
  const { type, id, action } = req.params;
  if (!isObjectType(type)) {
    return reply.code(404).send({ error: `unknown object type '${type}'` });
  }
  if (!isAction(action)) {
    return reply.code(404).send({ error: `unknown action '${action}'` });
  }
  const actionSpec = getActionSpec(action)!;
  // Per-action type restriction: appliesTo=[] means "any registered type".
  if (actionSpec.appliesTo.length > 0 && !actionSpec.appliesTo.includes(type)) {
    return reply
      .code(400)
      .send({ error: `action '${action}' does not apply to '${type}'` });
  }

  const validated = actionSpec.validate(bodyParams(req.body));
  if ("error" in validated) {
    return reply.code(400).send({ error: validated.error });
  }
  const params = validated.params;
  const actor = actorOf(req);
  const pool = getPool();

  // Perform the action's side effect (first cut: annotate persists a note; watch is recorded purely
  // via the audit row, which IS the watch state for now). The result is folded into the audit row.
  let result: Record<string, unknown>;
  try {
    if (action === "annotate") {
      const { annotationId } = await recordAnnotation(pool, {
        actor,
        objectType: type,
        objectId: id,
        note: String(params.note),
        tags: (params.tags as string[]) ?? [],
      });
      result = { annotationId, note: params.note, tags: params.tags ?? [] };
    } else {
      // watch
      result = { watched: Boolean(params.watched) };
    }
  } catch (err) {
    // A failed effect still gets audited (with the error) so the attempt is on record.
    const audit = await recordAction(pool, {
      actor,
      objectType: type,
      objectId: id,
      action,
      params,
      result: { error: (err as Error).message },
    });
    return reply
      .code(500)
      .send({ error: "action failed", action: audit });
  }

  const audit = await recordAction(pool, {
    actor,
    objectType: type,
    objectId: id,
    action,
    params,
    result,
  });
  return reply.send({ action: audit, result });
}
