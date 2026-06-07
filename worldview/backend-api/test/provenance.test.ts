import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  provenanceOf,
  isProvenanceLayer,
  PROVENANCE_LAYERS,
} from "../src/repositories/provenance.js";

// A capturing mock pool: records the last (sql, params) and returns a canned result. Mirrors the
// repo tests' shape-assertion style — no live DB required.
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

// A pool that raises Postgres undefined_table (42P01), to exercise graceful degradation.
function undefinedTablePool(): Pool {
  return {
    query: async () => {
      throw Object.assign(new Error("relation does not exist"), { code: "42P01" });
    },
  } as unknown as Pool;
}

const ROW = { entity_id: "4ca7b3", source: "opensky", ts: 1717795200, ingested_at: 1717795205 };

test("isProvenanceLayer / PROVENANCE_LAYERS expose the five stream layers", () => {
  for (const layer of ["adsb", "ais", "tle", "ew", "context"]) {
    assert.ok(isProvenanceLayer(layer), `${layer} should be supported`);
    assert.ok(PROVENANCE_LAYERS.includes(layer));
  }
  assert.equal(isProvenanceLayer("bogus"), false);
});

test("provenanceOf: SQL selects source + ingested_at, filters ts<=T, orders DESC, binds id+t", async () => {
  const captured = {} as Captured;
  const prov = await provenanceOf(mockPool([ROW], captured), "adsb", "4ca7b3", 1717795300);

  // Surfaces both provenance columns (source lineage + transaction time).
  assert.match(captured.sql, /\bsource\b/);
  assert.match(captured.sql, /extract\(epoch FROM ingested_at\) AS ingested_at/);
  // Valid time read back as epoch, last-known-at-T shape (ts <= to_timestamp($2), DESC, LIMIT 1).
  assert.match(captured.sql, /extract\(epoch FROM ts\) AS ts/);
  assert.match(captured.sql, /WHERE icao24 = \$1 AND ts <= to_timestamp\(\$2\)/);
  assert.match(captured.sql, /ORDER BY icao24, ts DESC/);
  assert.match(captured.sql, /LIMIT 1/);
  assert.match(captured.sql, /FROM adsb_positions/);
  // Params: entity id then T (UNIX seconds), in order.
  assert.deepEqual(captured.params, ["4ca7b3", 1717795300]);

  // Mapped result carries the bitemporal pair + lineage.
  assert.deepEqual(prov, {
    layer: "adsb",
    entityId: "4ca7b3",
    source: "opensky",
    ts: 1717795200,
    ingestedAt: 1717795205,
  });
});

test("provenanceOf: numeric-id layers coerce the entity id (mmsi/norad_id) and target the right table", async () => {
  const aisCap = {} as Captured;
  await provenanceOf(mockPool([ROW], aisCap), "ais", "636092297", 1000);
  assert.match(aisCap.sql, /FROM ais_positions/);
  assert.match(aisCap.sql, /WHERE mmsi = \$1/);
  assert.equal(aisCap.params[0], 636092297);
  assert.equal(typeof aisCap.params[0], "number");

  const tleCap = {} as Captured;
  await provenanceOf(mockPool([ROW], tleCap), "tle", "40115", 1000);
  assert.match(tleCap.sql, /FROM satellite_ephemeris/);
  assert.match(tleCap.sql, /WHERE norad_id = \$1/);
  assert.equal(tleCap.params[0], 40115);
});

test("provenanceOf: text-id layers (ew/context) keep the id as text", async () => {
  const ewCap = {} as Captured;
  await provenanceOf(mockPool([ROW], ewCap), "ew", "85283473fffffff", 1000);
  assert.match(ewCap.sql, /FROM gps_jamming/);
  assert.match(ewCap.sql, /WHERE h3_index = \$1/);
  assert.equal(ewCap.params[0], "85283473fffffff");

  const ctxCap = {} as Captured;
  await provenanceOf(mockPool([ROW], ctxCap), "context", "evt-1", 1000);
  assert.match(ctxCap.sql, /FROM geopolitical_events/);
  assert.match(ctxCap.sql, /WHERE event_id = \$1/);
  assert.equal(ctxCap.params[0], "evt-1");
});

test("provenanceOf: unknown layer returns null without querying", async () => {
  const captured = {} as Captured;
  const prov = await provenanceOf(mockPool([ROW], captured), "bogus", "x", 1000);
  assert.equal(prov, null);
  assert.equal(captured.sql, undefined); // never queried
});

test("provenanceOf: a non-numeric id for a numeric layer returns null without querying", async () => {
  const captured = {} as Captured;
  const prov = await provenanceOf(mockPool([ROW], captured), "ais", "not-a-number", 1000);
  assert.equal(prov, null);
  assert.equal(captured.sql, undefined);
});

test("provenanceOf: no matching row yields null", async () => {
  const captured = {} as Captured;
  const prov = await provenanceOf(mockPool([], captured), "adsb", "ffffff", 1000);
  assert.equal(prov, null);
});

test("provenanceOf: degrades to null on undefined_table (42P01) like history.ts", async () => {
  const prov = await provenanceOf(undefinedTablePool(), "adsb", "4ca7b3", 1000);
  assert.equal(prov, null);
});

test("provenanceOf: T defaults to ~now when omitted (still binds a numeric epoch)", async () => {
  const captured = {} as Captured;
  const before = Date.now() / 1000;
  await provenanceOf(mockPool([ROW], captured), "adsb", "4ca7b3");
  const after = Date.now() / 1000;
  const boundT = captured.params[1] as number;
  assert.equal(typeof boundT, "number");
  assert.ok(boundT >= before && boundT <= after, "default T should be ~now");
});
