import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import { exportReconstruction, exportCase } from "../src/repositories/export.js";
import type { FeatureCollection } from "../src/types.js";
import type {
  CaseBundle,
  ReconstructionBundle,
  ResolvedCaseItem,
} from "../src/repositories/export.js";

// Export-engine tests (tickets H19.2.7 + H19.4.6). The export repository is built on the other
// repositories (reconstruction.buildFrames, cases.*, ontology.getObject, ontologyAudit.listActions),
// all of which issue pool.query. We drive them with a single SQL-routing mock pool (no live Postgres)
// so we can assert the bundle SHAPES: reconstruction json/geojson, and case brief(Markdown)/geojson/json
// (items resolved to ontology objects, audited history included).

// A point feature row as the as-of-T history readers would return (ST_AsGeoJSON -> geojson string).
function adsbFeatureRow() {
  return {
    icao24: "abc123",
    ts: 1000,
    geojson: JSON.stringify({ type: "Point", coordinates: [10, 20] }),
  };
}

// Route a SQL string to canned rows covering the readers the export touches.
function routeSql(sql: string, params: unknown[]): Record<string, unknown>[] {
  // reconstruction handle
  if (/FROM reconstructions/.test(sql)) {
    return [
      {
        id: 1,
        title: "Strait replay",
        params: { from: 1000, to: 1100, stepSeconds: 100, bbox: null, layers: ["adsb"] },
        created_by: "alice",
        created_at: 1717795200,
      },
    ];
  }
  // history as-of-T reader (adsb) — one point feature per frame.
  if (/FROM adsb_positions/.test(sql)) return [adsbFeatureRow()];

  // case header
  if (/FROM cases/.test(sql) && /WHERE id = \$1/.test(sql)) {
    return [
      {
        id: 7,
        title: "Strait incident",
        description: "two dark vessels",
        status: "open",
        created_by: "alice",
        created_at: 1717795200,
        updated_at: 1717795200,
      },
    ];
  }
  if (/FROM case_members/.test(sql)) {
    return [{ case_id: 7, actor: "alice", role: "owner", added_at: 1717795200 }];
  }
  if (/FROM case_items/.test(sql)) {
    return [
      {
        id: 1,
        case_id: 7,
        object_type: "Vessel",
        object_id: "111",
        note: "primary",
        added_by: "alice",
        added_at: 1717795300,
      },
    ];
  }
  if (/FROM case_comments/.test(sql)) {
    return [{ id: 1, case_id: 7, actor: "bob", body: "I concur", created_at: 1717795400 }];
  }
  // ontology getObject for the Vessel item (dim-stream join). The registry's property bag carries no
  // lon/lat, so the geojson export emits a geometry-less Feature carrying the object's properties.
  if (/FROM vessels/.test(sql)) {
    return [
      {
        id: "111",
        mmsi: "111",
        name: "MV Test",
        __source: "ais",
        __ts: 1717795000,
        __ingested_at: 1717795001,
      },
    ];
  }
  // audited case history (ontology_actions filtered by Case/:id).
  if (/FROM ontology_actions/.test(sql)) {
    const [objectType, objectId] = params as [string, string];
    if (objectType === "Case" && objectId === "7") {
      return [
        {
          id: 1,
          ts: 1717795200,
          actor: "alice",
          object_type: "Case",
          object_id: "7",
          action: "case.create",
          params: {},
          result: null,
          source: "api",
          prev_hash: null,
          entry_hash: "h",
        },
      ];
    }
  }
  return [];
}

function mockPool(): Pool {
  return {
    query: async (sql: string, params: unknown[] = []) => {
      const rows = routeSql(sql, params);
      return { rows, rowCount: rows.length };
    },
  } as unknown as Pool;
}

// ---------------------------------------------------------------------------
// exportReconstruction
// ---------------------------------------------------------------------------

test("exportReconstruction json: manifest + re-derived frames", async () => {
  const res = await exportReconstruction(mockPool(), 1, "json");
  assert.ok(res);
  const body = res!.body as ReconstructionBundle;
  assert.equal(body.kind, "reconstruction");
  assert.equal(body.reconstruction.id, 1);
  // from=1000,to=1100,step=100 -> 2 frames (1000, 1100).
  assert.equal(body.frameCount, 2);
  assert.deepEqual(body.frames.map((f) => f.t), [1000, 1100]);
  assert.equal(body.frames[0]!.layers.adsb.type, "FeatureCollection");
});

test("exportReconstruction geojson: merged FeatureCollection stamps t + layer per feature", async () => {
  const res = await exportReconstruction(mockPool(), 1, "geojson");
  assert.ok(res);
  const fc = res!.body as FeatureCollection;
  assert.equal(fc.type, "FeatureCollection");
  // 2 frames x 1 adsb feature each = 2 features, each stamped with its frame t + layer.
  assert.equal(fc.features.length, 2);
  assert.deepEqual(fc.features.map((f) => f.properties.t).sort(), [1000, 1100]);
  assert.ok(fc.features.every((f) => f.properties.layer === "adsb"));
});

test("exportReconstruction: null when the reconstruction is absent", async () => {
  const empty = {
    query: async () => ({ rows: [], rowCount: 0 }),
  } as unknown as Pool;
  assert.equal(await exportReconstruction(empty, 999, "json"), null);
});

// ---------------------------------------------------------------------------
// exportCase
// ---------------------------------------------------------------------------

test("exportCase json: full bundle resolves items to ontology objects + includes audit history", async () => {
  const res = await exportCase(mockPool(), 7, "json");
  assert.ok(res);
  const body = res!.body as CaseBundle;
  assert.equal(body.kind, "case");
  assert.equal(body.case.id, 7);
  assert.equal(body.members.length, 1);
  assert.equal(body.comments.length, 1);
  // The pinned item is resolved to its current ontology object.
  assert.equal(body.items.length, 1);
  const resolved = body.items[0] as ResolvedCaseItem;
  assert.equal(resolved.item.objectType, "Vessel");
  assert.equal(resolved.object!.title, "MV Test");
  // The audited case history is present.
  assert.equal(body.history.length, 1);
  assert.equal(body.history[0]!.action, "case.create");
});

test("exportCase geojson: case items as a FeatureCollection (self-describing, geometry when positioned)", async () => {
  const res = await exportCase(mockPool(), 7, "geojson");
  assert.ok(res);
  const fc = res!.body as FeatureCollection;
  assert.equal(fc.type, "FeatureCollection");
  assert.equal(fc.features.length, 1);
  const f = fc.features[0]!;
  // Ontology objects aren't positioned points (no lon/lat in their property bag) -> null geometry, but
  // the feature still carries the item's identity + the resolved object's properties (self-describing).
  assert.equal(f.geometry, null);
  assert.equal(f.properties.objectType, "Vessel");
  assert.equal(f.properties.objectId, "111");
  assert.equal(f.properties.note, "primary");
  assert.equal(f.properties.title, "MV Test");
});


test("exportCase brief: structured Markdown with title, members, items+provenance, comments, audit", async () => {
  const res = await exportCase(mockPool(), 7, "brief");
  assert.ok(res);
  const { markdown } = res!.body as { markdown: string };
  assert.match(markdown, /# Case Brief: Strait incident/);
  assert.match(markdown, /## Summary/);
  assert.match(markdown, /\*\*Status:\*\* open/);
  assert.match(markdown, /## Members/);
  assert.match(markdown, /\*\*alice\*\* — owner/);
  assert.match(markdown, /## Pinned items/);
  assert.match(markdown, /MV Test/);
  assert.match(markdown, /\*\*Provenance:\*\* source=ais/);
  assert.match(markdown, /## Comments/);
  assert.match(markdown, /\*\*bob\*\*.*I concur/);
  assert.match(markdown, /## Audit trail/);
  assert.match(markdown, /`case.create` by alice/);
});

test("exportCase: null when the case is absent", async () => {
  const empty = {
    query: async () => ({ rows: [], rowCount: 0 }),
  } as unknown as Pool;
  assert.equal(await exportCase(empty, 999, "brief"), null);
});
