import test from "node:test";
import assert from "node:assert/strict";
import {
  buildBatchInsert,
  ADSB,
  AIS,
  TLE,
  EW,
  DARK_VESSEL,
  type Envelope,
} from "../src/repositories/historyWriter.js";

test("adsb batch: placeholders are renumbered across rows and params are ordered", () => {
  const env: Envelope = {
    domain: "adsb",
    source: "opensky",
    entity_id: "4ca7b3",
    ts: 1000,
    lon: 56.2,
    lat: 26.5,
    alt_m: 9000,
    payload: { gs_kt: 440, on_ground: false, is_military: false },
  };
  const { sql, params } = buildBatchInsert(ADSB, [env, env]);
  assert.equal(params.length, 28); // 14 per row × 2 rows
  assert.match(sql, /VALUES \(.+\), \(.+\)/);
  assert.match(sql, /\$28\)/); // last placeholder renumbered
  assert.match(sql, /ON CONFLICT \(icao24, ts\) DO NOTHING$/);
  assert.equal(params[0], 1000); // ts
  assert.equal(params[1], "4ca7b3"); // icao24
  assert.equal(params[2], 56.2); // lon
  assert.equal(params[3], 26.5); // lat
  assert.equal(params[4], 9000); // geom Z
});

test("adsb defaults: missing payload fields become null/false, alt Z defaults to 0", () => {
  const env: Envelope = {
    domain: "adsb",
    source: "s",
    entity_id: "abc",
    ts: 1,
    lon: 0,
    lat: 0,
    alt_m: null,
  };
  const { params } = buildBatchInsert(ADSB, [env]);
  assert.equal(params[4], 0); // Z falls back to 0 (geom is PointZ NOT NULL)
  assert.equal(params[5], null); // alt_m column stays null
  assert.equal(params[11], false); // on_ground default
  assert.equal(params[12], false); // is_military default
});

test("ais batch: mmsi is coerced to a number", () => {
  const env: Envelope = { domain: "ais", source: "s", entity_id: "636092297", ts: 5, lon: 1, lat: 2 };
  const { params } = buildBatchInsert(AIS, [env]);
  assert.equal(params[1], 636092297);
  assert.equal(typeof params[1], "number");
});

test("tle batch: footprint passed as WKT, norad coerced to number", () => {
  const env: Envelope = {
    domain: "tle",
    source: "celestrak",
    entity_id: "40115",
    ts: 9,
    lon: 1,
    lat: 2,
    alt_m: 500000,
    geom_wkt: "POLYGON((0 0,1 0,1 1,0 0))",
    payload: { sensor_type: "sar", velocity_kms: 7.5 },
  };
  const { sql, params } = buildBatchInsert(TLE, [env]);
  assert.match(sql, /ST_GeomFromText/);
  assert.equal(params[1], 40115);
  assert.equal(params[6], "sar");
  assert.equal(params[7], "POLYGON((0 0,1 0,1 1,0 0))");
});

test("ew batch: uses geom_wkt + intensity/sample_count from payload", () => {
  const env: Envelope = {
    domain: "ew",
    source: "gpsjam",
    entity_id: "85283473fffffff",
    ts: 7,
    geom_wkt: "POLYGON((0 0,1 0,1 1,0 0))",
    payload: { intensity: 0.8, sample_count: 12, h3_resolution: 5 },
  };
  const { params } = buildBatchInsert(EW, [env]);
  assert.equal(params[1], "85283473fffffff");
  assert.equal(params[2], 5);
  assert.equal(params[4], 0.8);
  assert.equal(params[5], 12);
});

test("dark-vessel batch: maps last-seen + extrapolated positions", () => {
  const env: Envelope = {
    domain: "context",
    source: "darkwatch",
    entity_id: "dark:999",
    ts: 1120,
    lon: 56.6,
    lat: 26.6,
    payload: {
      kind: "dark_vessel",
      mmsi: 999,
      geofence_id: 1,
      last_seen_ts: 900,
      last_lon: 56.5,
      last_lat: 26.6,
      gap_seconds: 220,
      status: "dark",
    },
  };
  const { sql, params } = buildBatchInsert(DARK_VESSEL, [env]);
  assert.match(sql, /dark_vessel_events/);
  assert.equal(params[1], 999); // mmsi
  assert.equal(params[4], 56.5); // last_seen lon
  assert.equal(params[7], 56.6); // extrapolated lon
  assert.equal(params[9], "dark");
});
