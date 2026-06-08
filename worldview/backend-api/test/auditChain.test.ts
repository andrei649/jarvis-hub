import test from "node:test";
import assert from "node:assert/strict";
import {
  GENESIS,
  canonicalize,
  computeEntryHash,
  stableStringify,
  verifyChain,
  type AuditChainRow,
  type StoredChainRow,
} from "../src/ontology/auditChain.js";

// Pure unit tests for the tamper-evident hash chain (ticket H19.4.4). No DB: these pin the hash
// construction (so it can be cross-checked / reimplemented) and prove that any mutation, removal or
// reordering of a row breaks verification at the FIRST offending id. Determinism is the crux —
// canonicalize must be invariant to JS object key-insertion order and jsonb round-tripping.

function row(over: Partial<AuditChainRow> = {}): AuditChainRow {
  return {
    id: 1,
    ts: 1717795200,
    actor: "andrei",
    objectType: "Aircraft",
    objectId: "4ca7b3",
    action: "annotate",
    params: { note: "x", tags: ["a"] },
    result: { annotationId: 9 },
    source: "api",
    ...over,
  };
}

// Build a valid chain from a list of AuditChainRows: prev_hash links + entry_hash per the module.
function buildChain(rows: AuditChainRow[]): StoredChainRow[] {
  const out: StoredChainRow[] = [];
  let prev: string | null = null;
  for (const r of rows) {
    const entryHash = computeEntryHash(prev, r);
    out.push({ ...r, prevHash: prev, entryHash });
    prev = entryHash;
  }
  return out;
}

test("stableStringify: sorts object keys recursively, preserves array order", () => {
  const a = stableStringify({ b: 1, a: { d: 2, c: 3 }, arr: [3, 1, 2] });
  const b = stableStringify({ arr: [3, 1, 2], a: { c: 3, d: 2 }, b: 1 });
  assert.equal(a, b); // key order in the input must not matter
  assert.equal(a, '{"a":{"c":3,"d":2},"arr":[3,1,2],"b":1}');
});

test("stableStringify: non-finite numbers and undefined-valued keys collapse to JSON-safe forms", () => {
  assert.equal(stableStringify(NaN), "null");
  assert.equal(stableStringify(Infinity), "null");
  assert.equal(stableStringify({ a: undefined, b: 1 }), '{"b":1}');
  assert.equal(stableStringify(null), "null");
});

test("canonicalize: identical for the same row regardless of jsonb key order (determinism)", () => {
  const r1 = row({ params: { note: "x", tags: ["a"], z: 1 }, result: { annotationId: 9, ok: true } });
  const r2 = row({ params: { z: 1, tags: ["a"], note: "x" }, result: { ok: true, annotationId: 9 } });
  assert.equal(canonicalize(r1), canonicalize(r2));
});

test("canonicalize: null actor/result render as distinct markers, not empty/object", () => {
  const c = canonicalize(row({ actor: null, result: null }));
  assert.match(c, /actor:\\null/);
  assert.match(c, /result:\\null/);
  // The null marker is distinct from a literal "null" string field (which is quoted).
  assert.notEqual(canonicalize(row({ actor: null })), canonicalize(row({ actor: "null" })));
});

test("computeEntryHash: genesis (null prev) === GENESIS-prefixed, hex, reproducible", () => {
  const r = row();
  const h1 = computeEntryHash(null, r);
  const h2 = computeEntryHash(GENESIS, r);
  assert.equal(h1, h2); // null is treated as GENESIS
  assert.match(h1, /^[0-9a-f]{64}$/); // sha256 hex
  assert.equal(computeEntryHash(null, r), h1); // reproducible
});

test("computeEntryHash: changing any field changes the hash", () => {
  const base = computeEntryHash("prev", row());
  assert.notEqual(base, computeEntryHash("prev", row({ action: "watch" })));
  assert.notEqual(base, computeEntryHash("prev", row({ params: { note: "y" } })));
  assert.notEqual(base, computeEntryHash("prev2", row())); // prev_hash is part of the hash
});

test("verifyChain: a clean chain verifies ok with the right count", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
  assert.deepEqual(verifyChain(chain), { ok: true, count: 3 });
});

test("verifyChain: empty chain is vacuously ok", () => {
  assert.deepEqual(verifyChain([]), { ok: true, count: 0 });
});

test("verifyChain: mutating a row's params breaks at that id (entry_hash mismatch)", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
  // Tamper with row id=2's params WITHOUT recomputing its stored entry_hash.
  chain[1] = { ...chain[1], params: { note: "TAMPERED" } };
  const res = verifyChain(chain);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAtId, 2);
  assert.match(res.reason!, /entry_hash mismatch/);
});

test("verifyChain: mutating a row's action breaks at that id", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 })]);
  chain[1] = { ...chain[1], action: "watch" };
  const res = verifyChain(chain);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAtId, 2);
});

test("verifyChain: removing a link is detected (broken prev_hash link)", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
  // Drop the middle row: row 3's prev_hash now points at a missing row 2's entry_hash.
  const without2 = [chain[0], chain[2]];
  const res = verifyChain(without2);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAtId, 3);
  assert.match(res.reason!, /broken link/);
});

test("verifyChain: reordering links is detected", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
  // verifyChain sorts by id, so to simulate a tamperer SWAPPING content while keeping ids, swap the
  // stored hashes/content of id 2 and id 3. After id-sort the prev links no longer chain.
  const swapped: StoredChainRow[] = [
    chain[0],
    { ...chain[2], id: 2 }, // id 2 now holds row-3's content+hashes
    { ...chain[1], id: 3 }, // id 3 now holds row-2's content+hashes
  ];
  const res = verifyChain(swapped);
  assert.equal(res.ok, false);
  // First break is at id 2 (its prev_hash links to the original row-2 hash, not row-1's).
  assert.equal(res.brokenAtId, 2);
});

test("verifyChain: a tampered genesis prev_hash is detected at the first id", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 })]);
  chain[0] = { ...chain[0], prevHash: "NOT_GENESIS" };
  const res = verifyChain(chain);
  assert.equal(res.ok, false);
  assert.equal(res.brokenAtId, 1);
  assert.match(res.reason!, /genesis prev_hash mismatch/);
});

test("verifyChain: tolerates input rows passed out of id order (sorts defensively)", () => {
  const chain = buildChain([row({ id: 1 }), row({ id: 2 }), row({ id: 3 })]);
  const shuffled = [chain[2], chain[0], chain[1]];
  assert.deepEqual(verifyChain(shuffled), { ok: true, count: 3 });
});
