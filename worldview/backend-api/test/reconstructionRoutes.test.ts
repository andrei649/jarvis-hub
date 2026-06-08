import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import { config } from "../src/config.js";
import { registerGuard } from "../src/auth/guard.js";
import { reconstructionRoutes } from "../src/routes/reconstruction.js";
import { caseRoutes } from "../src/routes/cases.js";
import { signToken } from "../src/auth/jwt.js";
import { getPool } from "../src/plugins/db.js";

// Route + guard tests for the reconstruction + export API (tickets H19.2.7 / H19.4.6). Proves:
//   * an analyst can SAVE a shareable reconstruction handle and READ its reproducible export bundle;
//   * a viewer can READ exports (read:export) but is 403 on CREATE (write:reconstruction);
//   * reproducibility: exporting the same handle twice yields the same frame timestamps;
//   * a case export (brief/geojson/json) is served and gated by read:export.
// A small STATEFUL in-memory mock pool stands in for Postgres (the repo's no-live-DB style), serving the
// reconstruction + case + audit statements the handlers issue.

const SECRET = "recon-route-secret";

interface Store {
  reconstructions: Record<string, unknown>[];
  cases: Record<string, unknown>[];
  members: Record<string, unknown>[];
  items: Record<string, unknown>[];
  comments: Record<string, unknown>[];
  actions: Record<string, unknown>[];
  reconSeq: number;
  caseSeq: number;
  actionSeq: number;
}

function freshStore(): Store {
  return {
    reconstructions: [],
    cases: [],
    members: [],
    items: [],
    comments: [],
    actions: [],
    reconSeq: 0,
    caseSeq: 0,
    actionSeq: 0,
  };
}

function exec(store: Store, sql: string, params: unknown[]): { rows: Record<string, unknown>[]; rowCount: number } {
  // audit hash chain
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
    const [objectType, objectId] = params as [string, string];
    const rows = store.actions
      .filter((a) => a.object_type === objectType && a.object_id === objectId)
      .map((a) => ({ ...a }))
      .reverse();
    return { rows, rowCount: rows.length };
  }

  // reconstructions
  if (/INSERT INTO reconstructions/.test(sql)) {
    store.reconSeq += 1;
    const row = {
      id: store.reconSeq,
      title: params[0],
      params: typeof params[1] === "string" ? JSON.parse(params[1] as string) : params[1],
      created_by: params[2],
      created_at: 1717795200,
    };
    store.reconstructions.push(row);
    return { rows: [row], rowCount: 1 };
  }
  if (/FROM reconstructions/.test(sql) && /WHERE id = \$1/.test(sql)) {
    const row = store.reconstructions.find((r) => r.id === Number(params[0]));
    return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
  }
  if (/FROM reconstructions/.test(sql)) {
    return { rows: [...store.reconstructions].reverse(), rowCount: store.reconstructions.length };
  }

  // history as-of-T reader (adsb) — one canned point feature per frame.
  if (/FROM adsb_positions/.test(sql)) {
    return {
      rows: [{ icao24: "abc", ts: params[0], geojson: JSON.stringify({ type: "Point", coordinates: [1, 2] }) }],
      rowCount: 1,
    };
  }

  // cases (minimal: header + members/items/comments empty)
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
  if (/INSERT INTO case_members/.test(sql)) {
    return { rows: [{ case_id: params[0], actor: params[1], role: params[2], added_at: 1717795200 }], rowCount: 1 };
  }
  if (/FROM cases/.test(sql) && /WHERE id = \$1/.test(sql)) {
    const row = store.cases.find((c) => c.id === Number(params[0]));
    return { rows: row ? [row] : [], rowCount: row ? 1 : 0 };
  }
  if (/FROM case_members/.test(sql)) return { rows: store.members, rowCount: store.members.length };
  if (/FROM case_items/.test(sql)) return { rows: store.items, rowCount: store.items.length };
  if (/FROM case_comments/.test(sql)) return { rows: store.comments, rowCount: store.comments.length };

  return { rows: [], rowCount: 0 };
}

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
  await app.register(reconstructionRoutes);
  await app.ready();
  return app;
}

function bearer(token: string): Record<string, string> {
  return { authorization: `Bearer ${token}` };
}

const VALID_BODY = { title: "Strait replay", from: 1000, to: 1200, stepSeconds: 100, layers: ["adsb"] };

test("auth ENABLED: analyst saves a reconstruction, viewer can export-read it (reproducible)", async () => {
  config.authSecret = SECRET;
  const store = freshStore();
  const restore = installStore(store);
  try {
    const app = await build();
    const analyst = signToken({ sub: "alice", role: "analyst" }, SECRET);
    const viewer = signToken({ sub: "val", role: "viewer" }, SECRET);

    // Analyst SAVES the handle (audited reconstruction.create).
    const create = await app.inject({
      method: "POST",
      url: "/reconstructions",
      headers: bearer(analyst),
      payload: VALID_BODY,
    });
    assert.equal(create.statusCode, 201);
    const id = create.json().reconstruction.id as number;
    assert.equal(create.json().reconstruction.createdBy, "alice");

    // Viewer READs the handle (read:export).
    const get = await app.inject({ method: "GET", url: `/reconstructions/${id}`, headers: bearer(viewer) });
    assert.equal(get.statusCode, 200);

    // Viewer EXPORTs json — frames re-derived from the saved params.
    const exp1 = await app.inject({
      method: "GET",
      url: `/reconstructions/${id}/export?format=json`,
      headers: bearer(viewer),
    });
    assert.equal(exp1.statusCode, 200);
    const b1 = exp1.json();
    assert.equal(b1.kind, "reconstruction");
    // from=1000,to=1200,step=100 -> 3 frames.
    assert.deepEqual(b1.frames.map((f: { t: number }) => f.t), [1000, 1100, 1200]);

    // REPRODUCIBILITY: a second export yields the same frame timestamps.
    const exp2 = await app.inject({
      method: "GET",
      url: `/reconstructions/${id}/export?format=json`,
      headers: bearer(viewer),
    });
    assert.deepEqual(
      exp2.json().frames.map((f: { t: number }) => f.t),
      b1.frames.map((f: { t: number }) => f.t),
    );

    // geojson export merges frames, stamping t + layer.
    const geo = await app.inject({
      method: "GET",
      url: `/reconstructions/${id}/export?format=geojson`,
      headers: bearer(viewer),
    });
    assert.equal(geo.statusCode, 200);
    assert.equal(geo.json().type, "FeatureCollection");
    assert.equal(geo.json().features.length, 3);

    // The save was audited (objectType Reconstruction).
    assert.ok(store.actions.some((a) => a.object_type === "Reconstruction" && a.action === "reconstruction.create"));

    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: a viewer is 403 on CREATE (write:reconstruction) but 200 on export-read", async () => {
  config.authSecret = SECRET;
  const store = freshStore();
  const restore = installStore(store);
  try {
    const app = await build();
    const viewer = signToken({ sub: "val", role: "viewer" }, SECRET);

    const denied = await app.inject({
      method: "POST",
      url: "/reconstructions",
      headers: bearer(viewer),
      payload: VALID_BODY,
    });
    assert.equal(denied.statusCode, 403);
    assert.match(denied.json().reason, /write:reconstruction/);

    // List (read:export) is allowed.
    const list = await app.inject({ method: "GET", url: "/reconstructions", headers: bearer(viewer) });
    assert.equal(list.statusCode, 200);

    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: a missing bearer is 401 on an export route (fail-closed)", async () => {
  config.authSecret = SECRET;
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/reconstructions" });
    assert.equal(res.statusCode, 401);
    await app.close();
  } finally {
    config.authSecret = "";
  }
});

test("auth ENABLED: case export (brief) is served as Markdown and gated by read:export", async () => {
  config.authSecret = SECRET;
  const store = freshStore();
  const restore = installStore(store);
  try {
    const app = await build();
    const analyst = signToken({ sub: "alice", role: "analyst" }, SECRET);
    const viewer = signToken({ sub: "val", role: "viewer" }, SECRET);

    const create = await app.inject({
      method: "POST",
      url: "/cases",
      headers: bearer(analyst),
      payload: { title: "Strait incident" },
    });
    const caseId = create.json().case.id as number;

    const brief = await app.inject({
      method: "GET",
      url: `/cases/${caseId}/export?format=brief`,
      headers: bearer(viewer),
    });
    assert.equal(brief.statusCode, 200);
    assert.match(brief.headers["content-type"] as string, /text\/markdown/);
    assert.match(brief.body, /# Case Brief: Strait incident/);

    const json = await app.inject({
      method: "GET",
      url: `/cases/${caseId}/export?format=json`,
      headers: bearer(viewer),
    });
    assert.equal(json.statusCode, 200);
    assert.equal(json.json().kind, "case");

    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("reconstruction routes validate inputs (400) before persisting", async () => {
  const app = Fastify();
  await app.register(reconstructionRoutes);
  await app.ready();

  const badParams = await app.inject({
    method: "POST",
    url: "/reconstructions",
    payload: { from: 200, to: 100, stepSeconds: 10, layers: ["adsb"] },
  });
  assert.equal(badParams.statusCode, 400);
  assert.match(badParams.json().error, /from.*before.*to/);

  const badFormat = await app.inject({ method: "GET", url: "/reconstructions/1/export?format=pdf" });
  assert.equal(badFormat.statusCode, 400);
  assert.match(badFormat.json().error, /json\|geojson/);

  const badId = await app.inject({ method: "GET", url: "/reconstructions/abc" });
  assert.equal(badId.statusCode, 400);

  await app.close();
});
