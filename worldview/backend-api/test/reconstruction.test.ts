import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  buildFrames,
  createReconstruction,
  getReconstruction,
  listReconstructions,
  validateParams,
  MAX_FRAMES,
  type ReconstructionParams,
} from "../src/repositories/reconstruction.js";

// Repository tests for the saved-reconstruction + replay layer (ticket H19.2.7). Capturing mock pool:
// createReconstruction uses pool.query for the INSERT and recordAction's transaction (pool.connect ->
// client BEGIN/lock/nextval/INSERT ontology_actions/COMMIT) for the audit. buildFrames calls the
// history as-of-T readers, which issue pool.query for the layer SQL — we count those to assert the
// frame stepping + cap. No live Postgres (matches the repo's no-DB style).
interface Captured {
  calls: { sql: string; params: unknown[] }[];
}

function mockPool(cap: Captured, rowsFor: (sql: string) => Record<string, unknown>[]): Pool {
  const clientQuery = async (sql: string, params: unknown[] = []) => {
    cap.calls.push({ sql, params });
    if (/nextval\('ontology_actions_id_seq'\)/.test(sql)) {
      return { rows: [{ id: 1, ts: 1717795200, tip_hash: null }], rowCount: 1 };
    }
    if (/INSERT INTO ontology_actions/.test(sql)) {
      return {
        rows: [
          {
            id: 1,
            ts: 1717795200,
            actor: "alice",
            object_type: "Reconstruction",
            object_id: "1",
            action: "reconstruction.create",
            params: {},
            result: null,
            source: "api",
            prev_hash: null,
            entry_hash: "h",
          },
        ],
        rowCount: 1,
      };
    }
    return { rows: [], rowCount: 0 };
  };
  return {
    query: async (sql: string, params: unknown[] = []) => {
      cap.calls.push({ sql, params });
      const rows = rowsFor(sql);
      return { rows, rowCount: rows.length };
    },
    connect: async () => ({ query: clientQuery, release: () => {} }),
  } as unknown as Pool;
}

function auditedAction(cap: Captured): { sql: string; params: unknown[] } | undefined {
  return cap.calls.find((c) => /INSERT INTO ontology_actions/.test(c.sql));
}

const VALID = {
  from: 1000,
  to: 1300,
  stepSeconds: 100,
  layers: ["adsb", "ais"],
};

// ---------------------------------------------------------------------------
// validateParams
// ---------------------------------------------------------------------------

test("validateParams: accepts a sane request and normalizes layers/bbox", () => {
  const res = validateParams({ ...VALID, bbox: { w: 1, s: 2, e: 3, n: 4 } });
  assert.ok("params" in res);
  if ("params" in res) {
    assert.equal(res.params.from, 1000);
    assert.equal(res.params.stepSeconds, 100);
    assert.deepEqual(res.params.layers, ["adsb", "ais"]);
    assert.deepEqual(res.params.bbox, { w: 1, s: 2, e: 3, n: 4 });
  }
});

test("validateParams: rejects from>=to, bad step, no layers, bad bbox, over-cap", () => {
  assert.ok("error" in validateParams({ ...VALID, from: 1300, to: 1000 }));
  assert.ok("error" in validateParams({ ...VALID, stepSeconds: 0 }));
  assert.ok("error" in validateParams({ ...VALID, layers: [] }));
  assert.ok("error" in validateParams({ ...VALID, layers: ["nope"] }));
  assert.ok("error" in validateParams({ ...VALID, bbox: { w: "x", s: 2, e: 3, n: 4 } }));
  // 0..1_000_000 by 1s would be ~1M frames — over MAX_FRAMES.
  assert.ok("error" in validateParams({ from: 0, to: 1_000_000, stepSeconds: 1, layers: ["adsb"] }));
});

test("validateParams: accepts a 'w,s,e,n' string bbox (the /history + MCP reconstruct_event form)", () => {
  const res = validateParams({ ...VALID, bbox: "1,2,3,4" });
  assert.ok("params" in res);
  if ("params" in res) assert.deepEqual(res.params.bbox, { w: 1, s: 2, e: 3, n: 4 });
  // a malformed comma-string is still rejected.
  assert.ok("error" in validateParams({ ...VALID, bbox: "1,2,3" }));
});

// ---------------------------------------------------------------------------
// createReconstruction
// ---------------------------------------------------------------------------

test("createReconstruction: INSERTs title/params/created_by and emits a reconstruction.create audit", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, (sql) =>
    /INSERT INTO reconstructions/.test(sql)
      ? [
          {
            id: 1,
            title: "Strait replay",
            params: { ...VALID, bbox: null },
            created_by: "alice",
            created_at: 1717795200,
          },
        ]
      : [],
  );
  const created = await createReconstruction(pool, {
    title: "Strait replay",
    params: VALID,
    actor: "alice",
  });
  const ins = cap.calls.find((c) => /INSERT INTO reconstructions/.test(c.sql))!;
  assert.ok(ins, "expected INSERT INTO reconstructions");
  assert.match(ins.sql, /INSERT INTO reconstructions \(title, params, created_by\)/);
  assert.match(ins.sql, /\$2::jsonb/);
  assert.equal(ins.params[0], "Strait replay");
  assert.equal(ins.params[2], "alice");

  const audit = auditedAction(cap);
  assert.ok(audit, "createReconstruction must emit an audit recordAction");
  assert.equal(audit!.params[3], "Reconstruction"); // object_type
  assert.equal(audit!.params[5], "reconstruction.create"); // action
  assert.equal(created.id, 1);
  assert.equal(created.createdBy, "alice");
});

test("createReconstruction: throws (no audit) on invalid params", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, () => []);
  await assert.rejects(
    () => createReconstruction(pool, { params: { ...VALID, from: 2, to: 1 }, actor: "alice" }),
    /from.*before.*to/,
  );
  assert.equal(auditedAction(cap), undefined, "no audit when validation fails");
  assert.equal(
    cap.calls.find((c) => /INSERT INTO reconstructions/.test(c.sql)),
    undefined,
    "no INSERT when validation fails",
  );
});

// ---------------------------------------------------------------------------
// getReconstruction / listReconstructions
// ---------------------------------------------------------------------------

test("getReconstruction: selects by id, normalizes stored params; null when absent / 42P01", async () => {
  const cap: Captured = { calls: [] };
  const hit = await getReconstruction(
    mockPool(cap, () => [
      { id: 1, title: "r", params: { ...VALID, bbox: null }, created_by: "a", created_at: 10 },
    ]),
    1,
  );
  assert.match(cap.calls[0].sql, /FROM reconstructions/);
  assert.match(cap.calls[0].sql, /WHERE id = \$1/);
  assert.equal(hit!.id, 1);
  assert.deepEqual(hit!.params.layers, ["adsb", "ais"]);

  const miss = await getReconstruction(mockPool({ calls: [] }, () => []), 99);
  assert.equal(miss, null);

  const fail = {
    query: async () => {
      throw Object.assign(new Error("nope"), { code: "42P01" });
    },
  } as unknown as Pool;
  assert.equal(await getReconstruction(fail, 1), null);
});

test("listReconstructions: newest first with a LIMIT; [] on 42P01", async () => {
  const cap: Captured = { calls: [] };
  await listReconstructions(mockPool(cap, () => []));
  assert.match(cap.calls[0].sql, /FROM reconstructions/);
  assert.match(cap.calls[0].sql, /ORDER BY created_at DESC, id DESC/);
  assert.match(cap.calls[0].sql, /LIMIT/);

  const fail = {
    query: async () => {
      throw Object.assign(new Error("nope"), { code: "42P01" });
    },
  } as unknown as Pool;
  assert.deepEqual(await listReconstructions(fail), []);
});

// ---------------------------------------------------------------------------
// buildFrames
// ---------------------------------------------------------------------------

test("buildFrames: steps from..to by stepSeconds, one as-of-T read per layer per frame", async () => {
  const cap: Captured = { calls: [] };
  // Each history reader issues a pool.query for its layer SQL; canned empty rows.
  const pool = mockPool(cap, () => []);
  const params: ReconstructionParams = {
    from: 1000,
    to: 1300,
    stepSeconds: 100,
    bbox: null,
    layers: ["adsb", "ais"],
  };
  const frames = await buildFrames(pool, params);
  // from=1000, to=1300, step=100 -> t = 1000,1100,1200,1300 = 4 frames.
  assert.equal(frames.length, 4);
  assert.deepEqual(frames.map((f) => f.t), [1000, 1100, 1200, 1300]);
  // Each frame carries a FeatureCollection per requested layer.
  for (const f of frames) {
    assert.equal(f.layers.adsb.type, "FeatureCollection");
    assert.equal(f.layers.ais.type, "FeatureCollection");
  }
  // The adsb as-of-T param ($1) is the frame epoch — UTC seconds passed straight through.
  const adsbReads = cap.calls.filter((c) => /FROM adsb_positions/.test(c.sql));
  assert.deepEqual(
    adsbReads.map((c) => c.params[0]),
    [1000, 1100, 1200, 1300],
  );
});

test("buildFrames: caps the number of frames at MAX_FRAMES (defensive)", async () => {
  const cap: Captured = { calls: [] };
  const pool = mockPool(cap, () => []);
  // Hand-built params that would otherwise produce way more than the cap.
  const params: ReconstructionParams = {
    from: 0,
    to: MAX_FRAMES * 10,
    stepSeconds: 1,
    bbox: null,
    layers: ["adsb"],
  };
  const frames = await buildFrames(pool, params);
  assert.equal(frames.length, MAX_FRAMES);
});

test("buildFrames: same params -> same frame timestamps (reproducibility)", async () => {
  const pool = mockPool({ calls: [] }, () => []);
  const params: ReconstructionParams = {
    from: 500,
    to: 800,
    stepSeconds: 150,
    bbox: null,
    layers: ["adsb"],
  };
  const a = await buildFrames(pool, params);
  const b = await buildFrames(pool, params);
  assert.deepEqual(
    a.map((f) => f.t),
    b.map((f) => f.t),
  );
});
