import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  fetchChain,
  listActions,
  recordAction,
  recordAnnotation,
  verifyAuditChain,
} from "../src/repositories/ontologyAudit.js";
import { computeEntryHash } from "../src/ontology/auditChain.js";

// Capturing mock pool. recordAction now runs INSIDE A TRANSACTION (BEGIN / advisory lock / read tip
// + next id / INSERT ... RETURNING / COMMIT) via pool.connect()->client, so the mock exposes a
// connect() returning a capturing client. The other functions (listActions/fetchChain/...) use
// pool.query directly, so the mock also keeps a top-level query. Both record (sql, params).
interface Captured {
  // Every (sql, params) seen, in order — lets a test find the INSERT among the txn statements.
  calls: { sql: string; params: unknown[] }[];
}

// A scripted client whose query() returns canned rows keyed by which SQL is running. `headRow`
// supplies the reserved id/ts + chain tip; `persisted` is the INSERT ... RETURNING row.
function mockPool(
  cap: Captured,
  opts: {
    headRow?: Record<string, unknown>;
    persisted?: Record<string, unknown>;
    queryRows?: Record<string, unknown>[]; // for direct pool.query (listActions/fetchChain)
  } = {},
): Pool {
  const head = opts.headRow ?? { id: 42, ts: 1717795200, tip_hash: null };
  const persisted = opts.persisted ?? PERSISTED;
  const clientQuery = async (sql: string, params: unknown[] = []) => {
    cap.calls.push({ sql, params });
    if (/nextval\('ontology_actions_id_seq'\)/.test(sql)) return { rows: [head], rowCount: 1 };
    if (/INSERT INTO ontology_actions/.test(sql)) return { rows: [persisted], rowCount: 1 };
    return { rows: [], rowCount: 0 }; // BEGIN / advisory lock / COMMIT
  };
  return {
    query: async (sql: string, params: unknown[] = []) => {
      cap.calls.push({ sql, params });
      return { rows: opts.queryRows ?? [persisted], rowCount: (opts.queryRows ?? [persisted]).length };
    },
    connect: async () => ({ query: clientQuery, release: () => {} }),
  } as unknown as Pool;
}

function undefinedTablePool(): Pool {
  const fail = async () => {
    throw Object.assign(new Error("relation does not exist"), { code: "42P01" });
  };
  return {
    query: fail,
    connect: async () => ({
      query: async (sql: string) => {
        // BEGIN / advisory lock succeed; the SELECT/INSERT against the table throw undefined_table.
        if (/^\s*(BEGIN|ROLLBACK|COMMIT)/i.test(sql) || /pg_advisory_xact_lock/.test(sql)) {
          return { rows: [], rowCount: 0 };
        }
        return fail();
      },
      release: () => {},
    }),
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
  prev_hash: null,
  entry_hash: "deadbeef",
};

function findInsert(cap: Captured): { sql: string; params: unknown[] } {
  const c = cap.calls.find((x) => /INSERT INTO ontology_actions/.test(x.sql));
  assert.ok(c, "expected an INSERT INTO ontology_actions");
  return c!;
}

test("recordAction: appends a chained audit row inside a txn, binds id/ts/prev_hash/entry_hash, jsonb-casts params/result", async () => {
  const cap: Captured = { calls: [] };
  const row = await recordAction(
    mockPool(cap, { headRow: { id: 42, ts: 1717795200, tip_hash: "prevtiphash" } }),
    {
      actor: "andrei",
      objectType: "Aircraft",
      objectId: "4ca7b3",
      action: "annotate",
      params: { note: "tracking", tags: ["watch"] },
      result: { annotationId: 9 },
    },
  );

  // Transaction shape: BEGIN, advisory lock, read tip+next-id, INSERT, COMMIT.
  const sqls = cap.calls.map((c) => c.sql).join(" | ");
  assert.match(sqls, /BEGIN/);
  assert.match(sqls, /pg_advisory_xact_lock/);
  assert.match(sqls, /nextval\('ontology_actions_id_seq'\)/);
  assert.match(sqls, /COMMIT/);

  const ins = findInsert(cap);
  // The INSERT now carries id/ts + the two chain columns (11 columns).
  assert.match(ins.sql, /\(id, ts, actor, object_type, object_id, action, params, result, source, prev_hash, entry_hash\)/);
  assert.match(ins.sql, /VALUES \(\$1, to_timestamp\(\$2\), \$3, \$4, \$5, \$6, \$7::jsonb, \$8::jsonb, \$9, \$10, \$11\)/);
  assert.match(ins.sql, /RETURNING id, extract\(epoch FROM ts\) AS ts/);
  assert.match(ins.sql, /prev_hash, entry_hash/);

  // Binds in column order; jsonb params JSON.stringify'd; prev_hash = the tip; entry_hash computed.
  assert.equal(ins.params[0], 42); // reserved id
  assert.equal(ins.params[1], 1717795200); // ts (UNIX seconds, fed to to_timestamp)
  assert.equal(ins.params[2], "andrei");
  assert.equal(ins.params[3], "Aircraft");
  assert.equal(ins.params[4], "4ca7b3");
  assert.equal(ins.params[5], "annotate");
  assert.equal(ins.params[6], JSON.stringify({ note: "tracking", tags: ["watch"] }));
  assert.equal(ins.params[7], JSON.stringify({ annotationId: 9 }));
  assert.equal(ins.params[8], "api");
  assert.equal(ins.params[9], "prevtiphash"); // prev_hash = the chain tip we read

  // entry_hash (param 11) is exactly computeEntryHash(prevHash, the row we're inserting).
  const expectedHash = computeEntryHash("prevtiphash", {
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
  assert.equal(ins.params[10], expectedHash);

  // Returns the persisted row mapped to camelCase with ts as UNIX seconds + chain fields.
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
    prevHash: null,
    entryHash: "deadbeef",
  });
});

test("recordAction: reserves an INTEGRAL ts (floor(epoch)::bigint) so a real-DB round-trip can't false-tamper", async () => {
  // The head SELECT must reserve whole UNIX seconds: the row stores to_timestamp(ts) and verify
  // re-derives extract(epoch FROM ts); only an integral seconds value round-trips byte-identically
  // through a microsecond timestamptz, so the hashed ts must NOT be a fractional epoch double.
  const cap: Captured = { calls: [] };
  await recordAction(mockPool(cap), {
    actor: null,
    objectType: "Aoi",
    objectId: "7",
    action: "watch",
    params: {},
  });
  const headSel = cap.calls.find((c) => /nextval\('ontology_actions_id_seq'\)/.test(c.sql))!;
  assert.match(headSel.sql, /floor\(extract\(epoch FROM now\(\)\)\)::bigint\s+AS ts/);
  // The bound ts (param $2, fed to to_timestamp) is exactly the integral value that was hashed —
  // the mock head supplies an integer, mirroring floor()::bigint, and it must pass through unrounded.
  const ins = findInsert(cap);
  assert.equal(ins.params[1], 1717795200);
  assert.equal(Number.isInteger(Number(ins.params[1])), true);
});

test("recordAction: genesis row binds prev_hash null (tip_hash NULL) and a GENESIS-based entry_hash", async () => {
  const cap: Captured = { calls: [] };
  await recordAction(mockPool(cap, { headRow: { id: 1, ts: 1717795200, tip_hash: null } }), {
    actor: null,
    objectType: "Aoi",
    objectId: "7",
    action: "watch",
    params: { watched: true },
  });
  const ins = findInsert(cap);
  assert.equal(ins.params[2], null); // null actor
  assert.equal(ins.params[7], null); // omitted result -> null
  assert.equal(ins.params[8], "api"); // default source
  assert.equal(ins.params[9], null); // genesis prev_hash
  // entry_hash uses GENESIS (prevHash null) for the first row.
  const expected = computeEntryHash(null, {
    id: 1,
    ts: 1717795200,
    actor: null,
    objectType: "Aoi",
    objectId: "7",
    action: "watch",
    params: { watched: true },
    result: null,
    source: "api",
  });
  assert.equal(ins.params[10], expected);
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

test("listActions: newest-first, optional object filters renumber binds, default limit, selects chain cols", async () => {
  const cap: Captured = { calls: [] };
  await listActions(mockPool(cap), { objectType: "Aircraft", objectId: "4ca7b3" });
  const c = cap.calls[0];
  assert.match(c.sql, /FROM ontology_actions/);
  assert.match(c.sql, /prev_hash, entry_hash/);
  assert.match(c.sql, /WHERE object_type = \$1 AND object_id = \$2/);
  assert.match(c.sql, /ORDER BY ts DESC, id DESC/);
  assert.match(c.sql, /LIMIT 200/);
  assert.deepEqual(c.params, ["Aircraft", "4ca7b3"]);
});

test("listActions: no filters -> no WHERE clause, empty params", async () => {
  const cap: Captured = { calls: [] };
  await listActions(mockPool(cap), {});
  const c = cap.calls[0];
  assert.doesNotMatch(c.sql, /WHERE/);
  assert.deepEqual(c.params, []);
});

test("listActions: degrades to [] on undefined_table (42P01)", async () => {
  const rows = await listActions(undefinedTablePool(), {});
  assert.deepEqual(rows, []);
});

test("fetchChain: selects chain columns ordered by id ASC (append order) for verification", async () => {
  const cap: Captured = { calls: [] };
  await fetchChain(mockPool(cap, { queryRows: [] }), {});
  const c = cap.calls[0];
  assert.match(c.sql, /FROM ontology_actions/);
  assert.match(c.sql, /prev_hash, entry_hash/);
  assert.match(c.sql, /ORDER BY id ASC/);
});

test("fetchChain: degrades to [] on undefined_table (42P01)", async () => {
  const rows = await fetchChain(undefinedTablePool(), {});
  assert.deepEqual(rows, []);
});

test("verifyAuditChain: empty/un-applied chain verifies ok (vacuously)", async () => {
  const cap: Captured = { calls: [] };
  const res = await verifyAuditChain(mockPool(cap, { queryRows: [] }));
  assert.deepEqual(res, { ok: true, count: 0 });
});

// ---------------------------------------------------------------------------
// verifyAuditChain: COMPLETE multi-page walk (review HIGH — a capped walk past
// VERIFY_PAGE_SIZE/MAX_FEATURES would return a false ok=true). We build a chain a touch longer than
// one page so verification MUST issue a second page, then prove (a) a clean long chain verifies and
// (b) tampering a row in the LATER page is detected — neither possible if verify stopped at the cap.
// ---------------------------------------------------------------------------

// A pool that serves a stored chain via keyset paging: each query carries `WHERE id > $1` + `LIMIT N`
// (parsed from the SQL), exactly the loop verifyAuditChain runs. Rows are pre-hashed valid links.
function pagingPool(rows: Record<string, unknown>[]): Pool {
  return {
    query: async (sql: string, params: unknown[] = []) => {
      const afterId = Number(params[0]); // `id > $1`
      const limitMatch = /LIMIT\s+(\d+)/i.exec(sql);
      const limit = limitMatch ? Number(limitMatch[1]) : rows.length;
      const page = rows.filter((r) => Number(r.id) > afterId).slice(0, limit);
      return { rows: page, rowCount: page.length };
    },
    connect: async () => ({ query: async () => ({ rows: [], rowCount: 0 }), release: () => {} }),
  } as unknown as Pool;
}

// Build a valid stored chain of `n` rows (id 1..n) as the DB would return them (snake_case columns,
// ts as UNIX seconds), with correct prev_hash/entry_hash links so verifyChain accepts it.
function buildStoredChain(n: number): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  let prev: string | null = null;
  for (let id = 1; id <= n; id++) {
    const chainRow = {
      id,
      ts: 1717795200 + id,
      actor: null,
      objectType: "Aircraft",
      objectId: String(id),
      action: "watch",
      params: { i: id },
      result: null,
      source: "api",
    };
    const entryHash = computeEntryHash(prev, chainRow);
    out.push({
      id,
      ts: chainRow.ts,
      actor: null,
      object_type: "Aircraft",
      object_id: String(id),
      action: "watch",
      params: { i: id },
      result: null,
      source: "api",
      prev_hash: prev,
      entry_hash: entryHash,
    });
    prev = entryHash;
  }
  return out;
}

// One row past the page size so the walk needs a SECOND page (VERIFY_PAGE_SIZE === MAX_FEATURES).
const MULTI_PAGE_N = 50001;

test("verifyAuditChain: a chain longer than one page is fully walked and verifies ok", async () => {
  const rows = buildStoredChain(MULTI_PAGE_N);
  const res = await verifyAuditChain(pagingPool(rows));
  assert.deepEqual(res, { ok: true, count: MULTI_PAGE_N });
});

test("verifyAuditChain: tampering a row in a LATER page is detected (not a false all-clear)", async () => {
  const rows = buildStoredChain(MULTI_PAGE_N);
  // Mutate a field of a row in the SECOND page — its stored entry_hash no longer matches its content.
  const tamperedId = MULTI_PAGE_N; // last row, well past the first page
  const victim = rows.find((r) => r.id === tamperedId)!;
  victim.action = "annotate"; // any content change breaks the integrity check
  const res = await verifyAuditChain(pagingPool(rows));
  assert.equal(res.ok, false);
  assert.equal(res.brokenAtId, tamperedId);
  assert.equal(res.count, MULTI_PAGE_N);
});

test("recordAnnotation: INSERTs the note + tags(jsonb) and returns the new annotation id", async () => {
  const cap: Captured = { calls: [] };
  const { annotationId } = await recordAnnotation(
    mockPool(cap, { queryRows: [{ id: 9 }] }),
    {
      actor: "andrei",
      objectType: "Aircraft",
      objectId: "4ca7b3",
      note: "tracking this military flight",
      tags: ["watch", "mil"],
    },
  );
  const c = cap.calls[0];
  assert.match(c.sql, /INSERT INTO ontology_annotations \(actor, object_type, object_id, note, tags\)/);
  assert.match(c.sql, /VALUES \(\$1, \$2, \$3, \$4, \$5::jsonb\)/);
  assert.equal(c.params[3], "tracking this military flight");
  assert.equal(c.params[4], JSON.stringify(["watch", "mil"]));
  assert.equal(annotationId, 9);
});
