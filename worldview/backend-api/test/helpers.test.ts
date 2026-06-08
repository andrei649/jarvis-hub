import test from "node:test";
import assert from "node:assert/strict";
import { isLayer, parseBBox, pointInBBox, LIVENESS_SECONDS } from "../src/types.js";
import { rowsToFeatureCollection, emptyCollection } from "../src/geojson.js";
import { envelopeToFeature, liveKey, geoKey, channel } from "../src/repositories/live.js";

test("isLayer guards the five known layers", () => {
  assert.ok(isLayer("adsb"));
  assert.ok(isLayer("context"));
  assert.equal(isLayer("bogus"), false);
});

test("parseBBox parses w,s,e,n and rejects bad input", () => {
  assert.deepEqual(parseBBox("55,25,58,28"), { w: 55, s: 25, e: 58, n: 28 });
  assert.equal(parseBBox(undefined), null);
  assert.equal(parseBBox("1,2,3"), null);
  assert.equal(parseBBox("a,b,c,d"), null);
});

test("parseBBox clamps to WGS84 ranges and reorders inverted bounds", () => {
  // Out-of-range values are clamped to [-180,180] / [-90,90].
  assert.deepEqual(parseBBox("-200,-100,200,100"), { w: -180, s: -90, e: 180, n: 90 });
  // An inverted (e<w, n<s) box is reordered.
  assert.deepEqual(parseBBox("58,28,55,25"), { w: 55, s: 25, e: 58, n: 28 });
});

test("pointInBBox includes points inside, excludes outside, and a null bbox matches all", () => {
  const box = { w: 55, s: 25, e: 58, n: 28 };
  assert.equal(pointInBBox(56, 26.5, box), true); // inside
  assert.equal(pointInBBox(55, 25, box), true); // on the boundary (inclusive)
  assert.equal(pointInBBox(60, 26, box), false); // east of bbox
  assert.equal(pointInBBox(56, 30, box), false); // north of bbox
  assert.equal(pointInBBox(0, 0, null), true); // no viewport => stream everything
});

test("each layer has a defined liveness window", () => {
  for (const layer of ["adsb", "ais", "tle", "ew", "context"] as const) {
    assert.equal(typeof LIVENESS_SECONDS[layer], "number");
  }
});

test("rowsToFeatureCollection parses the geojson column and keeps other columns as properties", () => {
  const fc = rowsToFeatureCollection([
    { icao24: "4ca7b3", alt_m: 9000, geojson: '{"type":"Point","coordinates":[56.2,26.5]}' },
  ]);
  assert.equal(fc.type, "FeatureCollection");
  assert.equal(fc.features.length, 1);
  assert.deepEqual(fc.features[0]!.geometry, { type: "Point", coordinates: [56.2, 26.5] });
  assert.equal(fc.features[0]!.properties.icao24, "4ca7b3");
  assert.equal(fc.features[0]!.properties.alt_m, 9000);
});

test("rowsToFeatureCollection parses extra geometry columns into properties", () => {
  const fc = rowsToFeatureCollection(
    [{ norad_id: 1, geojson: '{"type":"Point","coordinates":[0,0]}', footprint: '{"type":"Polygon","coordinates":[]}' }],
    "geojson",
    ["footprint"],
  );
  assert.deepEqual(fc.features[0]!.properties.footprint, { type: "Polygon", coordinates: [] });
});

test("emptyCollection is a valid empty FeatureCollection", () => {
  assert.deepEqual(emptyCollection(), { type: "FeatureCollection", features: [] });
});

test("live key helpers and envelopeToFeature", () => {
  assert.equal(liveKey("adsb", "4ca7b3"), "live:adsb:4ca7b3");
  assert.equal(geoKey("ais"), "geo:ais");
  assert.equal(channel("ew"), "chan:ew");
  const f = envelopeToFeature({ domain: "adsb", entity_id: "x", ts: 1, lon: 10, lat: 20, payload: { gs_kt: 5 } });
  assert.deepEqual(f.geometry, { type: "Point", coordinates: [10, 20] });
  assert.equal(f.properties.entity_id, "x");
  assert.equal(f.properties.gs_kt, 5);
});
