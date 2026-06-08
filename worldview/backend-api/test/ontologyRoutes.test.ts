import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import { ontologyRoutes } from "../src/routes/ontology.js";
import { getPool } from "../src/plugins/db.js";
import { computeEntryHash } from "../src/ontology/auditChain.js";

// Route-level tests for the ontology plugin. These exercise the registry surface + the validation
// guards (unknown type/action rejection, body-param validation) that DON'T touch the DB — so they
// run without a live Postgres, matching the repo's no-DB test style. The DB-backed projection/audit
// SQL is covered by ontology.test.ts / ontologyAudit.test.ts.

async function build(): Promise<FastifyInstance> {
  const app = Fastify();
  await app.register(ontologyRoutes);
  await app.ready();
  return app;
}

test("GET /ontology/types returns object/link/action descriptors", async () => {
  const app = await build();
  const res = await app.inject({ method: "GET", url: "/ontology/types" });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.objectTypes.length, 6);
  assert.equal(body.linkTypes.length, 3);
  assert.equal(body.actions.length, 2);
  await app.close();
});

test("GET /ontology/objects/:type rejects an unknown type with 404", async () => {
  const app = await build();
  const res = await app.inject({ method: "GET", url: "/ontology/objects/Bogus" });
  assert.equal(res.statusCode, 404);
  assert.match(res.json().error, /unknown object type/);
  await app.close();
});

test("GET /ontology/objects/:type rejects a non-numeric limit with 400", async () => {
  const app = await build();
  const res = await app.inject({ method: "GET", url: "/ontology/objects/Aircraft?limit=abc" });
  assert.equal(res.statusCode, 400);
  assert.match(res.json().error, /'limit' must be a number/);
  await app.close();
});

test("POST action rejects an unknown object type with 404 (before any DB write)", async () => {
  const app = await build();
  const res = await app.inject({
    method: "POST",
    url: "/ontology/objects/Bogus/4ca7b3/actions/annotate",
    payload: { note: "x" },
  });
  assert.equal(res.statusCode, 404);
  assert.match(res.json().error, /unknown object type/);
  await app.close();
});

test("POST action rejects an unknown action with 404 (before any DB write)", async () => {
  const app = await build();
  const res = await app.inject({
    method: "POST",
    url: "/ontology/objects/Aircraft/4ca7b3/actions/explode",
    payload: {},
  });
  assert.equal(res.statusCode, 404);
  assert.match(res.json().error, /unknown action/);
  await app.close();
});

test("POST annotate rejects a missing note with 400 (param validation, before any DB write)", async () => {
  const app = await build();
  const res = await app.inject({
    method: "POST",
    url: "/ontology/objects/Aircraft/4ca7b3/actions/annotate",
    payload: { tags: ["x"] },
  });
  assert.equal(res.statusCode, 400);
  assert.match(res.json().error, /'note' .* is required/);
  await app.close();
});

// Stub the shared pool so the route's writes are observed without a live Postgres. recordAnnotation
// uses pool.query; recordAction now runs in a TRANSACTION via pool.connect() (BEGIN / advisory lock /
// read next-id+tip / INSERT ... RETURNING / COMMIT), so we stub BOTH query and connect onto `seen`.
function stubWrites(
  pool: ReturnType<typeof getPool>,
  seen: { sql: string; params: unknown[] }[],
  auditRow: Record<string, unknown>,
): () => void {
  const originalQuery = pool.query;
  const originalConnect = pool.connect;
  const handle = async (sql: string, params: unknown[] = []) => {
    seen.push({ sql, params });
    if (/ontology_annotations/.test(sql)) return { rows: [{ id: 9 }], rowCount: 1 };
    if (/nextval\('ontology_actions_id_seq'\)/.test(sql)) {
      return { rows: [{ id: auditRow.id, ts: auditRow.ts, tip_hash: null }], rowCount: 1 };
    }
    if (/INSERT INTO ontology_actions/.test(sql)) return { rows: [auditRow], rowCount: 1 };
    return { rows: [], rowCount: 0 }; // BEGIN / advisory lock / COMMIT
  };
  (pool as unknown as { query: unknown }).query = handle;
  (pool as unknown as { connect: unknown }).connect = async () => ({
    query: handle,
    release: () => {},
  });
  return () => {
    (pool as unknown as { query: unknown }).query = originalQuery;
    (pool as unknown as { connect: unknown }).connect = originalConnect;
  };
}

test("POST annotate performs the action AND appends an audit row (the audited-endpoint guarantee)", async () => {
  const pool = getPool();
  const seen: { sql: string; params: unknown[] }[] = [];
  const restore = stubWrites(pool, seen, {
    id: 1,
    ts: 1717795200,
    actor: "andrei",
    object_type: "Aircraft",
    object_id: "4ca7b3",
    action: "annotate",
    params: { note: "watch this", tags: [] },
    result: { annotationId: 9 },
    source: "api",
    prev_hash: null,
    entry_hash: "deadbeef",
  });
  try {
    const app = await build();
    const res = await app.inject({
      method: "POST",
      url: "/ontology/objects/Aircraft/4ca7b3/actions/annotate",
      headers: { "x-actor": "andrei" },
      payload: { note: "watch this" },
    });
    assert.equal(res.statusCode, 200);
    const body = res.json();
    assert.equal(body.action.id, 1);
    assert.equal(body.action.action, "annotate");
    assert.equal(body.action.entryHash, "deadbeef");
    assert.equal(body.result.annotationId, 9);
    // Both writes happened: the annotation note, then the audit row.
    assert.ok(seen.some((c) => /INSERT INTO ontology_annotations/.test(c.sql)));
    assert.ok(seen.some((c) => /INSERT INTO ontology_actions/.test(c.sql)));
    await app.close();
  } finally {
    restore();
  }
});

// Build DB-shaped (snake_case) chain rows with valid prev_hash/entry_hash links, for the verify route.
function chainDbRows(): Record<string, unknown>[] {
  const base = (id: number) => ({
    id,
    ts: 1717795200 + id,
    actor: null,
    object_type: "Aircraft",
    object_id: "4ca7b3",
    action: "watch",
    params: { watched: true },
    result: { watched: true },
    source: "api",
  });
  const rows: Record<string, unknown>[] = [];
  let prev: string | null = null;
  for (let id = 1; id <= 3; id++) {
    const r = base(id);
    const entry = computeEntryHash(prev, {
      id: r.id,
      ts: r.ts,
      actor: r.actor,
      objectType: r.object_type,
      objectId: r.object_id,
      action: r.action,
      params: r.params,
      result: r.result,
      source: r.source,
    });
    rows.push({ ...r, prev_hash: prev, entry_hash: entry });
    prev = entry;
  }
  return rows;
}

test("GET /ontology/audit/verify returns ok for an intact hash chain", async () => {
  const pool = getPool();
  const original = pool.query;
  (pool as unknown as { query: unknown }).query = async () => ({
    rows: chainDbRows(),
    rowCount: 3,
  });
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/ontology/audit/verify" });
    assert.equal(res.statusCode, 200);
    assert.deepEqual(res.json(), { ok: true, count: 3 });
    await app.close();
  } finally {
    (pool as unknown as { query: unknown }).query = original;
  }
});

test("GET /ontology/audit/verify pinpoints the first broken link when a row is tampered", async () => {
  const pool = getPool();
  const original = pool.query;
  const rows = chainDbRows();
  // Tamper with row id=2's action WITHOUT updating its stored entry_hash.
  rows[1] = { ...rows[1], action: "annotate" };
  (pool as unknown as { query: unknown }).query = async () => ({ rows, rowCount: rows.length });
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/ontology/audit/verify" });
    assert.equal(res.statusCode, 200);
    const body = res.json();
    assert.equal(body.ok, false);
    assert.equal(body.brokenAtId, 2);
    assert.match(body.reason, /entry_hash mismatch/);
    await app.close();
  } finally {
    (pool as unknown as { query: unknown }).query = original;
  }
});

test("GET /ontology/audit/verify rejects a non-numeric limit with 400", async () => {
  const app = await build();
  const res = await app.inject({ method: "GET", url: "/ontology/audit/verify?limit=abc" });
  assert.equal(res.statusCode, 400);
  assert.match(res.json().error, /'limit' must be a number/);
  await app.close();
});

test("POST watch records an audit row even with no side-effect table (watch state = the audit row)", async () => {
  const pool = getPool();
  const seen: { sql: string; params: unknown[] }[] = [];
  const restore = stubWrites(pool, seen, {
    id: 2,
    ts: 1717795200,
    actor: null,
    object_type: "Aoi",
    object_id: "7",
    action: "watch",
    params: { watched: true },
    result: { watched: true },
    source: "api",
    prev_hash: null,
    entry_hash: "cafef00d",
  });
  try {
    const app = await build();
    const res = await app.inject({
      method: "POST",
      url: "/ontology/objects/Aoi/7/actions/watch",
      payload: {},
    });
    assert.equal(res.statusCode, 200);
    assert.equal(res.json().result.watched, true);
    assert.ok(seen.some((c) => /INSERT INTO ontology_actions/.test(c.sql)));
    await app.close();
  } finally {
    restore();
  }
});
