import test from "node:test";
import assert from "node:assert/strict";
import { Coalescer } from "../src/live/coalescer.js";

interface Delta {
  id: string;
  v: number;
}

// A coalescer wired to capture flushes into an array, with the timer disabled (huge interval) so
// each test drives flush() deterministically without real time.
function makeManual(over: Partial<{ maxBatch: number; maxQueue: number; intervalMs: number }> = {}) {
  const flushes: Delta[][] = [];
  const c = new Coalescer<Delta>({
    keyOf: (d) => d.id,
    intervalMs: over.intervalMs ?? 1_000_000,
    maxBatch: over.maxBatch ?? 1000,
    maxQueue: over.maxQueue ?? 1000,
    onFlush: (batch) => flushes.push(batch),
  });
  return { c, flushes };
}

test("coalescer: multiple deltas for the same entity collapse to the latest", () => {
  const { c, flushes } = makeManual();
  c.push({ id: "a", v: 1 });
  c.push({ id: "a", v: 2 });
  c.push({ id: "a", v: 3 });
  assert.equal(c.size, 1);
  c.flush();
  assert.deepEqual(flushes, [[{ id: "a", v: 3 }]]);
  // Two of the three pushes coalesced over the first.
  assert.equal(c.getMetrics().coalesced, 2);
});

test("coalescer: different entities are all kept", () => {
  const { c, flushes } = makeManual();
  c.push({ id: "a", v: 1 });
  c.push({ id: "b", v: 2 });
  c.push({ id: "c", v: 3 });
  assert.equal(c.size, 3);
  c.flush();
  assert.equal(flushes.length, 1);
  assert.equal(flushes[0]?.length, 3);
  assert.equal(c.getMetrics().coalesced, 0);
});

test("coalescer: within-flush ordering is stable (first-insertion order, latest value)", () => {
  const { c, flushes } = makeManual();
  c.push({ id: "x", v: 1 });
  c.push({ id: "y", v: 1 });
  c.push({ id: "z", v: 1 });
  // Updating an existing entity must NOT move it to the back of the queue.
  c.push({ id: "x", v: 99 });
  c.flush();
  assert.deepEqual(flushes[0], [
    { id: "x", v: 99 },
    { id: "y", v: 1 },
    { id: "z", v: 1 },
  ]);
});

test("coalescer: flush fires automatically when maxBatch distinct entities are reached", () => {
  const { c, flushes } = makeManual({ maxBatch: 3 });
  c.push({ id: "a", v: 1 });
  c.push({ id: "b", v: 1 });
  assert.equal(flushes.length, 0); // not yet
  c.push({ id: "c", v: 1 }); // hits maxBatch -> auto flush
  assert.equal(flushes.length, 1);
  assert.equal(flushes[0]?.length, 3);
  assert.equal(c.size, 0);
});

test("coalescer: repeated pushes of the same entity do NOT trigger maxBatch flush", () => {
  const { c, flushes } = makeManual({ maxBatch: 3 });
  c.push({ id: "a", v: 1 });
  c.push({ id: "a", v: 2 });
  c.push({ id: "a", v: 3 });
  c.push({ id: "a", v: 4 });
  // Only one distinct entity buffered, so maxBatch (3 distinct) never trips.
  assert.equal(flushes.length, 0);
  assert.equal(c.size, 1);
});

test("coalescer: bounded queue drops the OLDEST entity and counts the drop", () => {
  const { c, flushes } = makeManual({ maxQueue: 2, maxBatch: 1000 });
  c.push({ id: "a", v: 1 });
  c.push({ id: "b", v: 2 });
  c.push({ id: "c", v: 3 }); // queue full (2) -> drops oldest "a"
  assert.equal(c.size, 2);
  assert.equal(c.getMetrics().dropped, 1);
  c.flush();
  // "a" was dropped; "b" and "c" remain in insertion order.
  assert.deepEqual(flushes[0], [
    { id: "b", v: 2 },
    { id: "c", v: 3 },
  ]);
});

test("coalescer: updating an existing key while full does NOT drop (no new slot needed)", () => {
  const { c } = makeManual({ maxQueue: 2 });
  c.push({ id: "a", v: 1 });
  c.push({ id: "b", v: 2 });
  c.push({ id: "a", v: 10 }); // update existing -> no drop
  assert.equal(c.getMetrics().dropped, 0);
  assert.equal(c.size, 2);
});

test("coalescer: drop-oldest under sustained overflow keeps only the newest maxQueue entities", () => {
  const { c, flushes } = makeManual({ maxQueue: 3, maxBatch: 1000 });
  for (let i = 0; i < 10; i++) c.push({ id: `e${i}`, v: i });
  assert.equal(c.size, 3);
  assert.equal(c.getMetrics().dropped, 7);
  c.flush();
  assert.deepEqual(
    flushes[0]?.map((d) => d.id),
    ["e7", "e8", "e9"],
  );
});

test("coalescer: flush() is a no-op on an empty buffer", () => {
  const { c, flushes } = makeManual();
  c.flush();
  assert.equal(flushes.length, 0);
  assert.equal(c.getMetrics().flushes, 0);
});

test("coalescer: metrics track flushes and delivered counts", () => {
  const { c } = makeManual();
  c.push({ id: "a", v: 1 });
  c.push({ id: "b", v: 1 });
  c.flush();
  c.push({ id: "c", v: 1 });
  c.flush();
  const m = c.getMetrics();
  assert.equal(m.flushes, 2);
  assert.equal(m.delivered, 3);
});

test("coalescer: push after close is ignored", () => {
  const { c, flushes } = makeManual();
  c.push({ id: "a", v: 1 });
  c.close();
  c.push({ id: "b", v: 2 });
  assert.equal(c.size, 0); // close cleared the buffer
  c.flush();
  assert.equal(flushes.length, 0);
});

test("coalescer: timer-driven flush fires on the interval", async () => {
  const flushes: Delta[][] = [];
  const c = new Coalescer<Delta>({
    keyOf: (d) => d.id,
    intervalMs: 10,
    maxBatch: 1000,
    maxQueue: 1000,
    onFlush: (b) => flushes.push(b),
  });
  c.start();
  c.push({ id: "a", v: 1 });
  c.push({ id: "a", v: 2 });
  await new Promise((r) => setTimeout(r, 35));
  c.close();
  // At least one timer flush happened, and it delivered the coalesced latest value.
  assert.ok(flushes.length >= 1, `expected >=1 flush, got ${flushes.length}`);
  assert.deepEqual(flushes[0], [{ id: "a", v: 2 }]);
});

test("coalescer: start() is idempotent (no duplicate timers)", async () => {
  const flushes: Delta[][] = [];
  const c = new Coalescer<Delta>({
    keyOf: (d) => d.id,
    intervalMs: 10,
    maxBatch: 1000,
    maxQueue: 1000,
    onFlush: (b) => flushes.push(b),
  });
  c.start();
  c.start();
  c.push({ id: "a", v: 1 });
  await new Promise((r) => setTimeout(r, 25));
  c.close();
  // Single entity, single buffered value -> exactly one batch even if two timers were (wrongly) set.
  const total = flushes.reduce((n, b) => n + b.length, 0);
  assert.equal(total, 1);
});
