import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  listActions,
  recordAction,
  recordAnnotation,
} from "../src/repositories/ontologyAudit.js";

// Capturing mock pool (same shape as the other repo tests): records the (sql, params) and returns
// canned rows. recordAction does INSERT ... RETURNING, so the mock returns the persisted row.
interface Captured {
  sql: string;
  params: unknown[];
}

function mockPool(rows: Record<string, unknown>[], captured: Captured): Pool {
  return {
    query: async (sql: string, params: unknown[]) => {
      captured.sql = sql;
      captured.params = params;
      return { rows, rowCount: rows.length };
    },
  } as unknown as Pool;
}

function undefinedTablePool(): Pool {
  return {
    query: async () => {
      throw Object.assign(new Error("relation does not exist"), { code: "42P01" });
    },
  } as unknown as Pool;
}

const PERSISTED = {
  id: 42,
  ts: 1717795200,
  actor: "andrei",
  object_type: "Aircraft",
  object_id: "4ca7b3",
  action: "annotate",
  params: { note: "tracking", tags: ["watch"] },
  result: { annotationId: 9 },
  source: "api",
};

test("recordAction: appends an audit row (INSERT ... RETURNING), jsonb-casts params/result, binds in order", async () => {
  const cap = {} as Captured;
  const row = await recordAction(mockPool([PERSISTED], cap), {
    actor: "andrei",
    objectType: "Aircraft",
    objectId: "4ca7b3",
    action: "annotate",
    params: { note: "tracking", tags: ["watch"] },
    result: { annotationId: 9 },
  });

  // The audit write: INSERT into ontology_actions with the seven columns, jsonb casts on params/result.
  assert.match(cap.sql, /INSERT INTO ontology_actions/);
  assert.match(cap.sql, /\(actor, object_type, object_id, action, params, result, source\)/);
  assert.match(cap.sql, /VALUES \(\$1, \$2, \$3, \$4, \$5::jsonb, \$6::jsonb, \$7\)/);
  assert.match(cap.sql, /RETURNING id, extract\(epoch FROM ts\) AS ts/);
  // Binds in column order; jsonb params are JSON.stringify'd text; source defaults to 'api'.
  assert.equal(cap.params[0], "andrei");
  assert.equal(cap.params[1], "Aircraft");
  assert.equal(cap.params[2], "4ca7b3");
  assert.equal(cap.params[3], "annotate");
  assert.equal(cap.params[4], JSON.stringify({ note: "tracking", tags: ["watch"] }));
  assert.equal(cap.params[5], JSON.stringify({ annotationId: 9 }));
  assert.equal(cap.params[6], "api");

  // Returns the persisted row mapped to camelCase with ts as UNIX seconds.
  assert.deepEqual(row, {
    id: 42,
    ts: 1717795200,
    actor: "andrei",
    objectType: "Aircraft",
    objectId: "4ca7b3",
    action: "annotate",
    params: { note: "tracking", tags: ["watch"] },
    result: { annotationId: 9 },
    source: "api",
  });
});

test("recordAction: null actor + omitted result bind as null; default source 'api'", async () => {
  const cap = {} as Captured;
  await recordAction(mockPool([PERSISTED], cap), {
    actor: null,
    objectType: "Aoi",
    objectId: "7",
    action: "watch",
    params: { watched: true },
  });
  assert.equal(cap.params[0], null);
  assert.equal(cap.params[5], null); // omitted result -> null
  assert.equal(cap.params[6], "api");
});

test("recordAction: a missing audit table re-throws (the audit guarantee must surface)", async () => {
  await assert.rejects(
    () =>
      recordAction(undefinedTablePool(), {
        actor: null,
        objectType: "Aircraft",
        objectId: "x",
        action: "watch",
        params: {},
      }),
    /relation does not exist/,
  );
});

test("listActions: newest-first, optional object filters renumber binds, default limit", async () => {
  const cap = {} as Captured;
  await listActions(mockPool([PERSISTED], cap), { objectType: "Aircraft", objectId: "4ca7b3" });
  assert.match(cap.sql, /FROM ontology_actions/);
  assert.match(cap.sql, /WHERE object_type = \$1 AND object_id = \$2/);
  assert.match(cap.sql, /ORDER BY ts DESC, id DESC/);
  assert.match(cap.sql, /LIMIT 200/);
  assert.deepEqual(cap.params, ["Aircraft", "4ca7b3"]);
});

test("listActions: no filters -> no WHERE clause, empty params", async () => {
  const cap = {} as Captured;
  await listActions(mockPool([PERSISTED], cap), {});
  assert.doesNotMatch(cap.sql, /WHERE/);
  assert.deepEqual(cap.params, []);
});

test("listActions: degrades to [] on undefined_table (42P01)", async () => {
  const rows = await listActions(undefinedTablePool(), {});
  assert.deepEqual(rows, []);
});

test("recordAnnotation: INSERTs the note + tags(jsonb) and returns the new annotation id", async () => {
  const cap = {} as Captured;
  const { annotationId } = await recordAnnotation(mockPool([{ id: 9 }], cap), {
    actor: "andrei",
    objectType: "Aircraft",
    objectId: "4ca7b3",
    note: "tracking this military flight",
    tags: ["watch", "mil"],
  });
  assert.match(cap.sql, /INSERT INTO ontology_annotations \(actor, object_type, object_id, note, tags\)/);
  assert.match(cap.sql, /VALUES \(\$1, \$2, \$3, \$4, \$5::jsonb\)/);
  assert.equal(cap.params[3], "tracking this military flight");
  assert.equal(cap.params[4], JSON.stringify(["watch", "mil"]));
  assert.equal(annotationId, 9);
});
