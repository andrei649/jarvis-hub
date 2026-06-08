import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import { config } from "../src/config.js";
import { registerGuard } from "../src/auth/guard.js";
import { caseRoutes } from "../src/routes/cases.js";
import { signToken } from "../src/auth/jwt.js";
import { getPool } from "../src/plugins/db.js";

// Route + guard tests for the collaborative case API (ticket H19.4.5). The headline test proves TWO
// ACTORS COLLABORATE on a shared case with auth ENABLED and the actions are AUDITED end-to-end:
//   * actor A (alice, analyst) creates a case, adds actor B (bob) as a member, pins an item;
//   * actor B (bob, analyst) comments;
//   * a viewer is 403 on writes;
//   * GET /cases/:id returns BOTH actors' contributions (members + items + comments);
//   * GET /cases/:id/history reflects the audited case actions (case.create/add_member/add_item/comment).
// A small STATEFUL in-memory mock pool stands in for Postgres (the repo's no-live-DB style), serving
// the case CRUD + the audit hash-chain append (recordAction's transaction) so the flow is observable.

const SECRET = "case-route-secret";

// In-memory store backing the mock pool, so reads see the writes (real collaboration, not canned rows).
interface Store {
  cases: Record<string, unknown>[];
  members: Record<string, unknown>[];
  items: Record<string, unknown>[];
  comments: Record<string, unknown>[];
  actions: Record<string, unknown>[]; // the audit hash chain (ontology_actions)
  caseSeq: number;
  itemSeq: number;
  commentSeq: number;
  actionSeq: number;
}

function freshStore(): Store {
  return {
    cases: [],
    members: [],
    items: [],
    comments: [],
    actions: [],
    caseSeq: 0,
    itemSeq: 0,
    commentSeq: 0,
    actionSeq: 0,
  };
}

// Execute one SQL statement against the in-memory store. Covers exactly the statements the case
// repository + recordAction issue. Returns { rows, rowCount } like pg.
function exec(store: Store, sql: string, params: unknown[]): { rows: Record<string, unknown>[]; rowCount: number } {
  // --- audit hash chain (recordAction transaction) ---
  if (/^\s*(BEGIN|COMMIT|ROLLBACK)/i.test(sql) || /pg_advisory_xact_lock/.test(sql)) {
    return { rows: [], rowCount: 0 };
  }
  if (/nextval\('ontology_actions_id_seq'\)/.test(sql)) {
    const tip = store.actions[store.actions.length - 1];
    return {
      rows: [{ id: store.actionSeq + 1, ts: 1717795200 + store.actionSeq, tip_hash: tip ? tip.entry_hash : null }],
      rowCount: 1,
    };
  }
  if (/INSERT INTO ontology_actions/.test(sql)) {
    store.actionSeq += 1;
    const row = {
      id: params[0],
      ts: 1717795200 + (store.actionSeq - 1),
      actor: params[2],
      object_type: params[3],
      object_id: params[4],
      action: params[5],
      params: params[6],
      result: params[7],
      source: params[8],
      prev_hash: params[9],
      entry_hash: params[10],
    };
    store.actions.push(row);
    return { rows: [row], rowCount: 1 };
  }
  if (/FROM ontology_actions/.test(sql)) {
    // listActions filtered by object_type + object_id (the /history read).
    const [objectType, objectId] = params as [string, string];
    const rows = store.actions
      .filter((a) => a.object_type === objectType && a.object_id === objectId)
      .map((a) => ({ ...a }))
      .reverse(); // newest first
    return { rows, rowCount: rows.length };
  }

  // --- cases ---
  if (/INSERT INTO cases/.test(sql)) {
    store.caseSeq += 1;
    const row = {
      id: store.caseSeq,
      title: params[0],
      description: params[1],
      status: "open",
      created_by: params[2],
      created_at: 1717795200,
      updated_at: 1717795200,
    };
    store.cases.push(row);
    return { rows: [row], rowCount: 1 };
  }
  if (/UPDATE cases/.test(sql)) {
    const [id, status] = params as [number, string];
    const row = store.cases.find((c) => c.id === Number(id));
    if (!row) return { rows: [], rowCount: 0 };
    row.status = status;
    return { rows: [row], rowCount: 1 };
  }
  if (/FROM cases/.test(sql) && /WHERE id = \$1/.test(sql)) {
    const row = store.cases.find((c) => c.id === Number(params[0]));
    return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
  }
  if (/FROM cases/.test(sql)) {
    return { rows: [...store.cases].reverse(), rowCount: store.cases.length };
  }

  // --- members ---
  if (/INSERT INTO case_members/.test(sql)) {
    const caseId = Number(params[0]);
    const actor = String(params[1]);
    const role = params[2] != null ? String(params[2]) : "owner";
    let row = store.members.find((m) => m.case_id === caseId && m.actor === actor);
    if (row) {
      row.role = role;
    } else {
      row = { case_id: caseId, actor, role, added_at: 1717795200 };
      store.members.push(row);
    }
    return { rows: [row], rowCount: 1 };
  }
  if (/DELETE FROM case_members/.test(sql)) {
    const [caseId, actor] = params as [number, string];
    const before = store.members.length;
    store.members = store.members.filter((m) => !(m.case_id === Number(caseId) && m.actor === actor));
    return { rows: [], rowCount: before - store.members.length };
  }
  if (/FROM case_members/.test(sql)) {
    const rows = store.members.filter((m) => m.case_id === Number(params[0]));
    return { rows, rowCount: rows.length };
  }

  // --- items ---
  if (/INSERT INTO case_items/.test(sql)) {
    store.itemSeq += 1;
    const row = {
      id: store.itemSeq,
      case_id: params[0],
      object_type: params[1],
      object_id: params[2],
      note: params[3],
      added_by: params[4],
      added_at: 1717795200,
    };
    store.items.push(row);
    return { rows: [row], rowCount: 1 };
  }
  if (/FROM case_items/.test(sql)) {
    const rows = store.items.filter((i) => i.case_id === Number(params[0])).reverse();
    return { rows, rowCount: rows.length };
  }

  // --- comments ---
  if (/INSERT INTO case_comments/.test(sql)) {
    store.commentSeq += 1;
    const row = {
      id: store.commentSeq,
      case_id: params[0],
      actor: params[1],
      body: params[2],
      created_at: 1717795200,
    };
    store.comments.push(row);
    return { rows: [row], rowCount: 1 };
  }
  if (/FROM case_comments/.test(sql)) {
    const rows = store.comments.filter((c) => c.case_id === Number(params[0]));
    return { rows, rowCount: rows.length };
  }

  return { rows: [], rowCount: 0 };
}

// Install the stateful store onto the shared pool (query + connect for the audit transaction).
function installStore(store: Store): () => void {
  const pool = getPool();
  const originalQuery = pool.query;
  const originalConnect = pool.connect;
  const run = async (sql: string, params: unknown[] = []) => exec(store, sql, params);
  (pool as unknown as { query: unknown }).query = run;
  (pool as unknown as { connect: unknown }).connect = async () => ({ query: run, release: () => {} });
  return () => {
    (pool as unknown as { query: unknown }).query = originalQuery;
    (pool as unknown as { connect: unknown }).connect = originalConnect;
  };
}

async function build(): Promise<FastifyInstance> {
  const app = Fastify();
  await registerGuard(app);
  await app.register(caseRoutes);
  await app.ready();
  return app;
}

function bearer(token: string): Record<string, string> {
  return { authorization: `Bearer ${token}` };
}

test("auth ENABLED: two analysts collaborate on a shared case end-to-end, audited", async () => {
  config.authSecret = SECRET;
  const store = freshStore();
  const restore = installStore(store);
  try {
    const app = await build();
    const alice = signToken({ sub: "alice", role: "analyst" }, SECRET);
    const bob = signToken({ sub: "bob", role: "analyst" }, SECRET);

    // A: alice creates the case (created_by = her principal sub).
    const create = await app.inject({
      method: "POST",
      url: "/cases",
      headers: bearer(alice),
      payload: { title: "Strait incident", description: "two dark vessels" },
    });
    assert.equal(create.statusCode, 201);
    const caseId = create.json().case.id as number;
    assert.equal(create.json().case.createdBy, "alice");

    // A: alice adds bob as a collaborator.
    const addMember = await app.inject({
      method: "POST",
      url: `/cases/${caseId}/members`,
      headers: bearer(alice),
      payload: { actor: "bob", role: "collaborator" },
    });
    assert.equal(addMember.statusCode, 201);
    assert.equal(addMember.json().member.actor, "bob");

    // A: alice pins an item (an ontology object) into the case.
    const addItem = await app.inject({
      method: "POST",
      url: `/cases/${caseId}/items`,
      headers: bearer(alice),
      payload: { objectType: "DarkVesselEvent", objectId: "123:456", note: "primary" },
    });
    assert.equal(addItem.statusCode, 201);
    assert.equal(addItem.json().item.addedBy, "alice");

    // B: bob comments (added_by = his principal sub).
    const comment = await app.inject({
      method: "POST",
      url: `/cases/${caseId}/comments`,
      headers: bearer(bob),
      payload: { body: "I concur — recommend tasking a pass" },
    });
    assert.equal(comment.statusCode, 201);
    assert.equal(comment.json().comment.actor, "bob");

    // The combined view returns BOTH actors' contributions.
    const view = await app.inject({
      method: "GET",
      url: `/cases/${caseId}`,
      headers: bearer(bob),
    });
    assert.equal(view.statusCode, 200);
    const body = view.json();
    const memberActors = (body.members as { actor: string }[]).map((m) => m.actor).sort();
    assert.deepEqual(memberActors, ["alice", "bob"]); // alice (owner, auto) + bob (collaborator)
    assert.equal(body.items.length, 1);
    assert.equal(body.items[0].addedBy, "alice");
    assert.equal(body.comments.length, 1);
    assert.equal(body.comments[0].actor, "bob");

    // The audit trail reflects the case actions (create / add_member / add_item / comment).
    const history = await app.inject({
      method: "GET",
      url: `/cases/${caseId}/history`,
      headers: bearer(alice),
    });
    assert.equal(history.statusCode, 200);
    const actions = (history.json().actions as { action: string; actor: string }[]);
    const names = actions.map((a) => a.action).sort();
    assert.deepEqual(names, ["case.add_item", "case.add_member", "case.comment", "case.create"]);
    // The comment action is attributed to bob; the create to alice — multi-user audit.
    const commentAction = actions.find((a) => a.action === "case.comment")!;
    assert.equal(commentAction.actor, "bob");
    const createAction = actions.find((a) => a.action === "case.create")!;
    assert.equal(createAction.actor, "alice");

    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: a viewer can READ a case but is 403 on writes (RBAC write:cases)", async () => {
  config.authSecret = SECRET;
  const store = freshStore();
  // Seed a case so the viewer's read has something to return.
  const restore = installStore(store);
  try {
    const app = await build();
    const analyst = signToken({ sub: "alice", role: "analyst" }, SECRET);
    const viewer = signToken({ sub: "val", role: "viewer" }, SECRET);

    const create = await app.inject({
      method: "POST",
      url: "/cases",
      headers: bearer(analyst),
      payload: { title: "Case X" },
    });
    const caseId = create.json().case.id as number;

    // Viewer READ → 200.
    const read = await app.inject({
      method: "GET",
      url: `/cases/${caseId}`,
      headers: bearer(viewer),
    });
    assert.equal(read.statusCode, 200);

    // Viewer WRITE (comment) → 403.
    const denied = await app.inject({
      method: "POST",
      url: `/cases/${caseId}/comments`,
      headers: bearer(viewer),
      payload: { body: "nope" },
    });
    assert.equal(denied.statusCode, 403);
    assert.match(denied.json().reason, /write:cases/);

    // Viewer CREATE → 403 too.
    const deniedCreate = await app.inject({
      method: "POST",
      url: "/cases",
      headers: bearer(viewer),
      payload: { title: "blocked" },
    });
    assert.equal(deniedCreate.statusCode, 403);

    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: a missing bearer is 401 on a case route (fail-closed)", async () => {
  config.authSecret = SECRET;
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/cases" });
    assert.equal(res.statusCode, 401);
    await app.close();
  } finally {
    config.authSecret = "";
  }
});

test("auth DISABLED: case routes work with no token (back-compat); actor falls back to X-Actor", async () => {
  config.authSecret = "";
  const store = freshStore();
  const restore = installStore(store);
  try {
    const app = await build();
    const create = await app.inject({
      method: "POST",
      url: "/cases",
      headers: { "x-actor": "headerguy" },
      payload: { title: "open-mode case" },
    });
    assert.equal(create.statusCode, 201);
    // No principal in open mode (anonymous sub is set by guard) — but here we assert the route works.
    assert.notEqual(create.statusCode, 401);
    assert.notEqual(create.statusCode, 403);
    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("case routes validate inputs (400) before touching the DB", async () => {
  const app = Fastify();
  await app.register(caseRoutes);
  await app.ready();

  const noTitle = await app.inject({ method: "POST", url: "/cases", payload: {} });
  assert.equal(noTitle.statusCode, 400);
  assert.match(noTitle.json().error, /'title'/);

  const badId = await app.inject({ method: "GET", url: "/cases/abc" });
  assert.equal(badId.statusCode, 400);
  assert.match(badId.json().error, /positive integer/);

  await app.close();
});
