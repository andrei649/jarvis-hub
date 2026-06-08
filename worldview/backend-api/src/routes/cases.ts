import type { FastifyInstance, FastifyRequest } from "fastify";
import { getPool } from "../plugins/db.js";
import {
  addComment,
  addItem,
  addMember,
  createCase,
  getCase,
  listCases,
  listComments,
  listItems,
  listMembers,
  removeMember,
  updateCaseStatus,
  type CaseMemberRole,
  type CaseStatus,
} from "../repositories/cases.js";
import { listActions } from "../repositories/ontologyAudit.js";
import type { Principal } from "../auth/rbac.js";

// Collaborative CASE API (ticket H19.4.5 "Cases / annotations / multi-user"). Case files let two (or
// more) analysts work a shared case: MEMBERS (the collaborating roster), ITEMS (ontology objects/events
// pinned in) and COMMENTS (the thread). Every MUTATING endpoint records a row on the existing
// tamper-evident audit hash chain (objectType 'Case'), so the case history is auditable — read it back
// via GET /cases/:id/history (a filtered view of /ontology/actions) or verified via the same chain.
//
// Access is gated CENTRALLY by the auth guard against the route->permission map in rbac.ts
// (read:cases = viewer+, write:cases = analyst+); handlers here just resolve the acting identity.

interface IdParams {
  id: string;
}
interface MemberParams {
  id: string;
  actor: string;
}
interface ListQuery {
  limit?: string;
}

const VALID_STATUS: ReadonlySet<string> = new Set(["open", "closed", "archived"]);
const VALID_MEMBER_ROLE: ReadonlySet<string> = new Set(["owner", "collaborator", "viewer"]);

// The acting identity for created_by/added_by/comments: the authenticated principal's `sub` if present,
// else an `X-Actor` header, else null. Centralized so every write records a consistent actor.
function actorOf(req: FastifyRequest): string | null {
  const principal = (req as FastifyRequest & { principal?: Principal }).principal;
  if (principal && principal.sub && principal.sub.trim()) return principal.sub.trim();
  const h = req.headers["x-actor"];
  if (typeof h === "string" && h.trim()) return h.trim();
  return null;
}

// Parse a :id path param to a positive integer, or null when it isn't one (→ 400).
function parseId(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

// Guard body parsing: Fastify pre-parses JSON, but a non-object body (array/string/null) would break
// field access — coerce to {} so handlers see a plain record.
function bodyOf(body: unknown): Record<string, unknown> {
  if (body && typeof body === "object" && !Array.isArray(body)) {
    return body as Record<string, unknown>;
  }
  return {};
}

export async function caseRoutes(app: FastifyInstance): Promise<void> {
  const pool = () => getPool();

  // POST /cases — create a case (audited case.create). title required.
  app.post("/cases", async (req, reply) => {
    const body = bodyOf(req.body);
    const title = typeof body.title === "string" ? body.title.trim() : "";
    if (!title) {
      return reply.code(400).send({ error: "'title' (non-empty string) is required" });
    }
    const description = typeof body.description === "string" ? body.description : null;
    const created = await createCase(pool(), { title, description, actor: actorOf(req) });
    return reply.code(201).send({ case: created });
  });

  // GET /cases?limit= — list cases, newest first.
  app.get<{ Querystring: ListQuery }>("/cases", async (req, reply) => {
    const limit = req.query.limit ? Number(req.query.limit) : undefined;
    if (limit !== undefined && Number.isNaN(limit)) {
      return reply.code(400).send({ error: "'limit' must be a number" });
    }
    const cases = await listCases(pool(), { limit });
    return reply.send({ cases });
  });

  // GET /cases/:id — the case plus its members, items and comments (the collaborative view).
  app.get<{ Params: IdParams }>("/cases/:id", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const found = await getCase(pool(), id);
    if (!found) return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
    const [members, items, comments] = await Promise.all([
      listMembers(pool(), id),
      listItems(pool(), id),
      listComments(pool(), id),
    ]);
    return reply.send({ case: found, members, items, comments });
  });

  // PATCH /cases/:id — change status (open/closed/archived); audited (case.close/archive/open).
  app.patch<{ Params: IdParams }>("/cases/:id", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const body = bodyOf(req.body);
    const status = typeof body.status === "string" ? body.status : "";
    if (!VALID_STATUS.has(status)) {
      return reply
        .code(400)
        .send({ error: "'status' must be one of open|closed|archived" });
    }
    const updated = await updateCaseStatus(pool(), {
      id,
      status: status as CaseStatus,
      actor: actorOf(req),
    });
    if (!updated) return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
    return reply.send({ case: updated });
  });

  // POST /cases/:id/members — add (or re-role) a member; audited (case.add_member).
  app.post<{ Params: IdParams }>("/cases/:id/members", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    if (!(await getCase(pool(), id))) {
      return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
    }
    const body = bodyOf(req.body);
    const member = typeof body.actor === "string" ? body.actor.trim() : "";
    if (!member) {
      return reply.code(400).send({ error: "'actor' (non-empty string) is required" });
    }
    const roleRaw = typeof body.role === "string" ? body.role : "collaborator";
    if (!VALID_MEMBER_ROLE.has(roleRaw)) {
      return reply
        .code(400)
        .send({ error: "'role' must be one of owner|collaborator|viewer" });
    }
    const added = await addMember(pool(), {
      caseId: id,
      member,
      role: roleRaw as CaseMemberRole,
      actor: actorOf(req),
    });
    return reply.code(201).send({ member: added });
  });

  // GET /cases/:id/members — the case roster.
  app.get<{ Params: IdParams }>("/cases/:id/members", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const members = await listMembers(pool(), id);
    return reply.send({ members });
  });

  // DELETE /cases/:id/members/:actor — remove a member; audited (case.remove_member).
  app.delete<{ Params: MemberParams }>("/cases/:id/members/:actor", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const member = req.params.actor;
    if (!member || !member.trim()) {
      return reply.code(400).send({ error: "'actor' is required" });
    }
    const removed = await removeMember(pool(), {
      caseId: id,
      member: member.trim(),
      actor: actorOf(req),
    });
    if (!removed) {
      return reply.code(404).send({ error: `actor '${member}' is not a member of case '${id}'` });
    }
    return reply.send({ removed: true });
  });

  // POST /cases/:id/items — pin an ontology object/event into the case; audited (case.add_item).
  app.post<{ Params: IdParams }>("/cases/:id/items", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    if (!(await getCase(pool(), id))) {
      return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
    }
    const body = bodyOf(req.body);
    const objectType = typeof body.objectType === "string" ? body.objectType.trim() : "";
    const objectId = typeof body.objectId === "string" ? body.objectId.trim() : "";
    if (!objectType || !objectId) {
      return reply
        .code(400)
        .send({ error: "'objectType' and 'objectId' (non-empty strings) are required" });
    }
    const note = typeof body.note === "string" ? body.note : null;
    const item = await addItem(pool(), {
      caseId: id,
      objectType,
      objectId,
      note,
      actor: actorOf(req),
    });
    return reply.code(201).send({ item });
  });

  // GET /cases/:id/items — the pinned objects/events.
  app.get<{ Params: IdParams }>("/cases/:id/items", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const items = await listItems(pool(), id);
    return reply.send({ items });
  });

  // POST /cases/:id/comments — add a comment to the thread; audited (case.comment).
  app.post<{ Params: IdParams }>("/cases/:id/comments", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    if (!(await getCase(pool(), id))) {
      return reply.code(404).send({ error: `no case with id '${req.params.id}'` });
    }
    const body = bodyOf(req.body);
    const text = typeof body.body === "string" ? body.body.trim() : "";
    if (!text) {
      return reply.code(400).send({ error: "'body' (non-empty string) is required" });
    }
    const comment = await addComment(pool(), { caseId: id, body: text, actor: actorOf(req) });
    return reply.code(201).send({ comment });
  });

  // GET /cases/:id/comments — the discussion thread (oldest first).
  app.get<{ Params: IdParams }>("/cases/:id/comments", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const comments = await listComments(pool(), id);
    return reply.send({ comments });
  });

  // GET /cases/:id/history — the audited case actions for this case (a filtered view of the
  // tamper-evident ontology_actions chain: objectType='Case', objectId=:id). Proves the collaboration
  // is end-to-end audited. Gated by read:cases.
  app.get<{ Params: IdParams }>("/cases/:id/history", async (req, reply) => {
    const id = parseId(req.params.id);
    if (id === null) return reply.code(400).send({ error: "'id' must be a positive integer" });
    const actions = await listActions(pool(), {
      objectType: "Case",
      objectId: String(id),
    });
    return reply.send({ actions });
  });
}
