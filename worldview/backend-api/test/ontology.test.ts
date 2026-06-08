import test from "node:test";
import assert from "node:assert/strict";
import type { Pool } from "pg";
import {
  getObject,
  linksOf,
  listObjects,
} from "../src/repositories/ontology.js";
import {
  describeRegistry,
  isObjectType,
  isAction,
  OBJECT_TYPE_NAMES,
  LINK_TYPE_NAMES,
  ACTION_NAMES,
} from "../src/ontology/registry.js";

// Capturing mock pool (same shape as provenance.test.ts): records every (sql, params) call and
// returns canned rows. The ontology repo issues multiple queries for links, so we capture a list.
interface Call {
  sql: string;
  params: unknown[];
}

function mockPool(rows: Record<string, unknown>[], calls: Call[]): Pool {
  return {
    query: async (sql: string, params: unknown[]) => {
      calls.push({ sql, params });
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

// --- Registry ---------------------------------------------------------------

test("registry exposes the six object types, three link types, and the two actions", () => {
  for (const t of ["Aircraft", "Vessel", "Satellite", "Aoi", "ReconWindow", "DarkVesselEvent"]) {
    assert.ok(isObjectType(t), `${t} should be a registered object type`);
    assert.ok(OBJECT_TYPE_NAMES.includes(t));
  }
  assert.equal(isObjectType("Bogus"), false);
  assert.deepEqual(LINK_TYPE_NAMES, ["covers", "wentDark", "inGeofence"]);
  for (const a of ["annotate", "watch"]) {
    assert.ok(isAction(a));
    assert.ok(ACTION_NAMES.includes(a));
  }
  assert.equal(isAction("nope"), false);
});

test("describeRegistry returns object/link/action descriptors for GET /ontology/types", () => {
  const reg = describeRegistry();
  assert.equal(reg.objectTypes.length, 6);
  assert.equal(reg.linkTypes.length, 3);
  assert.equal(reg.actions.length, 2);
  const aircraft = reg.objectTypes.find((o) => o.type === "Aircraft");
  assert.equal(aircraft?.kind, "dim-stream");
  assert.equal(aircraft?.table, "aircraft");
  const covers = reg.linkTypes.find((l) => l.type === "covers");
  assert.equal(covers?.fromType, "Satellite");
  assert.equal(covers?.toType, "Aoi");
});

// --- listObjects: dim-stream shape (Aircraft) -------------------------------

const AIRCRAFT_ROW = {
  icao24: "4ca7b3",
  registration: "A6-EOA",
  type_code: "A388",
  operator: "Emirates",
  is_military: false,
  callsign: "UAE201",
  alt_m: 11000,
  gs_kt: 480,
  track_deg: 270,
  on_ground: false,
  __source: "opensky",
  __ts: 1717795200,
  __ingested_at: 1717795205,
};

test("listObjects(Aircraft): dim LEFT JOIN LATERAL latest stream, DISTINCT-ON-style ts DESC, limit bind", async () => {
  const calls: Call[] = [];
  const objects = await listObjects(mockPool([AIRCRAFT_ROW], calls), "Aircraft", { limit: 25 });

  const { sql, params } = calls[0]!;
  assert.match(sql, /FROM aircraft d/);
  assert.match(sql, /LEFT JOIN LATERAL/);
  assert.match(sql, /FROM adsb_positions/);
  assert.match(sql, /ORDER BY ts DESC/); // latest stream fix per aircraft
  assert.match(sql, /LIMIT \$1/);
  assert.match(sql, /s\.source AS __source/);
  assert.match(sql, /extract\(epoch FROM s\.ts\) AS __ts/);
  assert.match(sql, /extract\(epoch FROM s\.ingested_at\) AS __ingested_at/);
  assert.deepEqual(params, [25]); // clamped limit bound as $1

  // Mapped object JSON: id/type/title/properties/provenance.
  const obj = objects[0]!;
  assert.equal(obj.id, "4ca7b3");
  assert.equal(obj.type, "Aircraft");
  assert.equal(obj.title, "A6-EOA");
  assert.equal(obj.properties.callsign, "UAE201");
  assert.equal(obj.properties.isMilitary, false);
  assert.deepEqual(obj.provenance, {
    source: "opensky",
    ts: 1717795200,
    ingestedAt: 1717795205,
  });
});

test("listObjects: unknown type returns [] without querying", async () => {
  const calls: Call[] = [];
  const objects = await listObjects(mockPool([], calls), "Bogus");
  assert.deepEqual(objects, []);
  assert.equal(calls.length, 0);
});

test("listObjects: default limit clamps to 500 when omitted", async () => {
  const calls: Call[] = [];
  await listObjects(mockPool([AIRCRAFT_ROW], calls), "Aircraft");
  assert.deepEqual(calls[0]!.params, [500]);
});

test("listObjects: degrades to [] on undefined_table (42P01)", async () => {
  const objects = await listObjects(undefinedTablePool(), "Aircraft");
  assert.deepEqual(objects, []);
});

// --- getObject: numeric-id coercion + table type provenance -----------------

test("getObject(Vessel): coerces mmsi to number, binds id, filters WHERE d.mmsi = $1", async () => {
  const calls: Call[] = [];
  const row = { mmsi: 636092297, name: "EVER GIVEN", __source: "ais-feed", __ts: 10, __ingested_at: 11 };
  const obj = await getObject(mockPool([row], calls), "Vessel", "636092297");
  const { sql, params } = calls[0]!;
  assert.match(sql, /FROM vessels d/);
  assert.match(sql, /WHERE d\.mmsi = \$1/);
  assert.equal(params[0], 636092297);
  assert.equal(typeof params[0], "number");
  assert.equal(obj?.id, "636092297");
  assert.equal(obj?.title, "EVER GIVEN");
});

test("getObject: a non-numeric id for a numeric type returns null without querying", async () => {
  const calls: Call[] = [];
  const obj = await getObject(mockPool([], calls), "Satellite", "not-a-number");
  assert.equal(obj, null);
  assert.equal(calls.length, 0);
});

test("getObject(ReconWindow): single-table projection with synthetic id + provenance from ts/source", async () => {
  const calls: Call[] = [];
  const row = {
    id: "40115:aoi-strait:1717795200",
    norad_id: 40115,
    aoi_id: "aoi-strait",
    sensor_type: "optical",
    t_ingress: 1717795200,
    t_peak: 1717795260,
    t_egress: 1717795320,
    min_distance_km: 12.5,
    sunlit_at_peak: true,
    quality: 0.9,
    source: "recon-predictor",
    ts: 1717795260,
    ingested_at: 1717795261,
  };
  const obj = await getObject(mockPool([row], calls), "ReconWindow", "40115:aoi-strait:1717795200");
  const { sql, params } = calls[0]!;
  assert.match(sql, /FROM recon_windows/);
  assert.match(sql, /WHERE \(norad_id \|\| ':' \|\| aoi_id \|\| ':' \|\| extract\(epoch FROM t_ingress\)\) = \$1/);
  assert.doesNotMatch(sql, /::bigint/); // no rounding of the composite-id epoch
  assert.equal(params[0], "40115:aoi-strait:1717795200");
  assert.equal(obj?.type, "ReconWindow");
  assert.equal(obj?.title, "Recon 40115 → aoi-strait");
  assert.equal(obj?.properties.minDistanceKm, 12.5);
  // table-type provenance comes from the row's source/ts/ingested_at aliases.
  assert.deepEqual(obj?.provenance, {
    source: "recon-predictor",
    ts: 1717795260,
    ingestedAt: 1717795261,
  });
});

test("getObject(Aoi): dimension-only type has null provenance", async () => {
  const calls: Call[] = [];
  const row = { id: 7, name: "Strait of Hormuz", category: "chokepoint", dark_gap_seconds: 1800, created_at: 5 };
  const obj = await getObject(mockPool([row], calls), "Aoi", "7");
  assert.match(calls[0]!.sql, /FROM geofences/);
  assert.equal(obj?.title, "Strait of Hormuz");
  assert.deepEqual(obj?.provenance, { source: null, ts: null, ingestedAt: null });
});

test("getObject: no row yields null", async () => {
  const calls: Call[] = [];
  const obj = await getObject(mockPool([], calls), "Aircraft", "ffffff");
  assert.equal(obj, null);
});

// --- linksOf: derived edges -------------------------------------------------

test("linksOf(Satellite): covers edges from recon_windows, bound by norad_id", async () => {
  const calls: Call[] = [];
  const row = {
    aoi_id: "aoi-strait",
    t_ingress: 100,
    t_peak: 150,
    t_egress: 200,
    min_distance_km: 8.1,
    quality: 0.77,
  };
  const links = await linksOf(mockPool([row], calls), "Satellite", "40115");
  const { sql, params } = calls[0]!;
  assert.match(sql, /FROM recon_windows/);
  assert.match(sql, /WHERE norad_id = \$1/);
  assert.equal(params[0], 40115);
  assert.equal(links.length, 1);
  assert.deepEqual(links[0], {
    type: "covers",
    fromType: "Satellite",
    fromId: "40115",
    toType: "Aoi",
    toId: "aoi-strait",
    properties: { tIngress: 100, tPeak: 150, tEgress: 200, minDistanceKm: 8.1, quality: 0.77 },
  });
});

test("linksOf(Vessel): wentDark edges from dark_vessel_events, synthetic event id from SQL", async () => {
  const calls: Call[] = [];
  // The canonical id is generated by Postgres (mmsi || ':' || extract(epoch FROM ts)); the mock
  // supplies that text as event_id rather than the resolver rebuilding it from a float in JS.
  const row = {
    geofence_id: 7,
    gap_seconds: 3600,
    status: "dark",
    ts: 1717795200,
    event_id: "636092297:1717795200",
  };
  const links = await linksOf(mockPool([row], calls), "Vessel", "636092297");
  const { sql } = calls[0]!;
  assert.match(sql, /FROM dark_vessel_events/);
  assert.match(sql, /WHERE mmsi = \$1/);
  // toId must come from the SQL id expression, not a JS-reconstructed float.
  assert.match(sql, /\(mmsi \|\| ':' \|\| extract\(epoch FROM ts\)\) AS event_id/);
  assert.equal(calls[0]!.params[0], 636092297);
  assert.equal(links[0]!.type, "wentDark");
  assert.equal(links[0]!.toType, "DarkVesselEvent");
  assert.equal(links[0]!.toId, "636092297:1717795200");
});

test("linksOf(DarkVesselEvent): inGeofence edge matches the full canonical id (no to_timestamp)", async () => {
  const calls: Call[] = [];
  const links = await linksOf(mockPool([{ geofence_id: 7 }], calls), "DarkVesselEvent", "636092297:1717795200");
  const { sql, params } = calls[0]!;
  assert.match(sql, /FROM dark_vessel_events/);
  // mmsi prefilter (indexed) AND full-id match by the same expression — never to_timestamp/float eq.
  assert.match(sql, /WHERE mmsi = \$1 AND \(mmsi \|\| ':' \|\| extract\(epoch FROM ts\)\) = \$2/);
  assert.doesNotMatch(sql, /to_timestamp/);
  assert.deepEqual(params, [636092297, "636092297:1717795200"]);
  assert.equal(links[0]!.type, "inGeofence");
  assert.equal(links[0]!.toType, "Aoi");
  assert.equal(links[0]!.toId, "7");
});

// --- Regression: FRACTIONAL-second epoch (microsecond timestamps from the live DB) --------------
// The original bug: ::bigint rounded the composite-id epoch and the resolver rebuilt toId from a JS
// float, so a DarkVesselEvent's canonical id (rounded) didn't equal the wentDark link's toId (full
// float), and darkInGeofence's to_timestamp(rounded) never matched the stored fractional ts → zero
// edges. With whole-second epochs the rounding+reconstruction agreed, hiding the bug. This test pins
// the FULL-epoch path: the same Postgres-rendered id expression flows through getObject/listObjects,
// the wentDark toId, and the darkInGeofence match — all byte-identical for a microsecond timestamp.
const FRAC_EPOCH = 1780865129.713659;
const FRAC_EVENT_ID = `412331100:${FRAC_EPOCH}`; // "412331100:1780865129.713659"

test("regression: fractional-epoch DarkVesselEvent id is consistent across object + wentDark + inGeofence", async () => {
  // (1) getObject(DarkVesselEvent) returns the canonical id Postgres generated (mock echoes it).
  {
    const calls: Call[] = [];
    const row = {
      id: FRAC_EVENT_ID,
      mmsi: 412331100,
      geofence_id: 7,
      last_seen_ts: FRAC_EPOCH - 60,
      gap_seconds: 1800,
      status: "dark",
      source: "ais-feed",
      ts: FRAC_EPOCH,
      ingested_at: FRAC_EPOCH + 1,
    };
    const obj = await getObject(mockPool([row], calls), "DarkVesselEvent", FRAC_EVENT_ID);
    // The getObject WHERE binds the un-rounded id expression and the bound id verbatim (no float math).
    const { sql, params } = calls[0]!;
    assert.match(sql, /WHERE \(mmsi \|\| ':' \|\| extract\(epoch FROM ts\)\) = \$1/);
    assert.doesNotMatch(sql, /::bigint/);
    assert.equal(params[0], FRAC_EVENT_ID);
    assert.equal(obj?.id, FRAC_EVENT_ID); // canonical id round-trips unrounded
  }

  // (2) Vessel -wentDark-> DarkVesselEvent: toId equals that SAME canonical id (from SQL event_id).
  {
    const calls: Call[] = [];
    const row = {
      geofence_id: 7,
      gap_seconds: 1800,
      status: "dark",
      ts: FRAC_EPOCH,
      event_id: FRAC_EVENT_ID, // Postgres-rendered id text — what the live DB returns
    };
    const links = await linksOf(mockPool([row], calls), "Vessel", "412331100");
    assert.match(calls[0]!.sql, /\(mmsi \|\| ':' \|\| extract\(epoch FROM ts\)\) AS event_id/);
    assert.doesNotMatch(calls[0]!.sql, /::bigint/);
    assert.equal(links[0]!.toId, FRAC_EVENT_ID);
    // The link's toId IS the DarkVesselEvent canonical id → Vessel→wentDark→getObject is navigable.
    assert.equal(links[0]!.toId, FRAC_EVENT_ID);
  }

  // (3) DarkVesselEvent -inGeofence-> Aoi: matches by full id, binding the fractional id verbatim.
  {
    const calls: Call[] = [];
    const links = await linksOf(mockPool([{ geofence_id: 7 }], calls), "DarkVesselEvent", FRAC_EVENT_ID);
    const { sql, params } = calls[0]!;
    assert.match(sql, /WHERE mmsi = \$1 AND \(mmsi \|\| ':' \|\| extract\(epoch FROM ts\)\) = \$2/);
    assert.doesNotMatch(sql, /to_timestamp/);
    // mmsi prefilter parsed from the id's first segment; full fractional id bound as-is (no rounding).
    assert.deepEqual(params, [412331100, FRAC_EVENT_ID]);
    assert.equal(links.length, 1); // edge IS found for the fractional-second id
    assert.equal(links[0]!.toId, "7");
  }
});

test("linksOf: object types with no outgoing link types return [] without querying", async () => {
  const calls: Call[] = [];
  // Aircraft has no fromType link in the registry.
  const links = await linksOf(mockPool([], calls), "Aircraft", "4ca7b3");
  assert.deepEqual(links, []);
  assert.equal(calls.length, 0);
});

test("linksOf: degrades to [] on undefined_table (42P01)", async () => {
  const links = await linksOf(undefinedTablePool(), "Satellite", "40115");
  assert.deepEqual(links, []);
});
