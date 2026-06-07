import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import { ontologyRoutes } from "../src/routes/ontology.js";
import { getPool } from "../src/plugins/db.js";

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

// End-to-end acceptance: a valid action endpoint WRITES an audit row. We swap the shared pool's
// `query` for a capturing stub (the lazy pg.Pool never connects unless queried), so the route's
// recordAnnotation + recordAction calls are observed without a live Postgres.
test("POST annotate performs the action AND appends an audit row (the audited-endpoint guarantee)", async () => {
  const pool = getPool();
  const seen: { sql: string; params: unknown[] }[] = [];
  const original = pool.query;
  // Stub: annotation INSERT returns id 9; audit INSERT ... RETURNING returns a persisted row.
  (pool as unknown as { query: unknown }).query = async (sql: string, params: unknown[]) => {
    seen.push({ sql, params });
    if (/ontology_annotations/.test(sql)) return { rows: [{ id: 9 }], rowCount: 1 };
    return {
      rows: [
        {
          id: 1,
          ts: 1717795200,
          actor: "andrei",
          object_type: "Aircraft",
          object_id: "4ca7b3",
          action: "annotate",
          params: { note: "watch this", tags: [] },
          result: { annotationId: 9 },
          source: "api",
        },
      ],
      rowCount: 1,
    };
  };
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
    assert.equal(body.result.annotationId, 9);
    // Both writes happened: the annotation note, then the audit row.
    assert.ok(seen.some((c) => /INSERT INTO ontology_annotations/.test(c.sql)));
    assert.ok(seen.some((c) => /INSERT INTO ontology_actions/.test(c.sql)));
    await app.close();
  } finally {
    (pool as unknown as { query: unknown }).query = original;
  }
});

test("POST watch records an audit row even with no side-effect table (watch state = the audit row)", async () => {
  const pool = getPool();
  const seen: { sql: string; params: unknown[] }[] = [];
  const original = pool.query;
  (pool as unknown as { query: unknown }).query = async (sql: string, params: unknown[]) => {
    seen.push({ sql, params });
    return {
      rows: [
        {
          id: 2,
          ts: 1717795200,
          actor: null,
          object_type: "Aoi",
          object_id: "7",
          action: "watch",
          params: { watched: true },
          result: { watched: true },
          source: "api",
        },
      ],
      rowCount: 1,
    };
  };
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
    (pool as unknown as { query: unknown }).query = original;
  }
});
