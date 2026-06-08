import test from "node:test";
import assert from "node:assert/strict";
import {
  encodeGeohash,
  cellSizeDegrees,
  viewportCells,
  geoChannel,
  MAX_VIEWPORT_CELLS,
} from "../src/live/geohash.js";

test("encodeGeohash: matches known reference geohashes", () => {
  // Cross-checked against the canonical geohash algorithm / public references.
  assert.equal(encodeGeohash(-5.6, 42.6, 5), "ezs42"); // classic Wikipedia example
  assert.equal(encodeGeohash(-0.1257, 51.5085, 6), "gcpvj0"); // London
  assert.equal(encodeGeohash(0, 0, 5), "s0000"); // null island
  // Prefix property: a longer geohash starts with the shorter one for the same point.
  assert.equal(encodeGeohash(-5.6, 42.6, 3), "ezs");
  assert.ok(encodeGeohash(-74.0445, 40.6892, 6).startsWith("dr5r")); // NYC harbor
});

test("encodeGeohash: precision controls length", () => {
  for (const p of [1, 2, 3, 5, 8]) {
    assert.equal(encodeGeohash(12.3, 45.6, p).length, p);
  }
});

test("encodeGeohash: precision is a prefix chain (each longer hash extends the shorter)", () => {
  const lon = 13.404954;
  const lat = 52.520008; // Berlin
  const h3 = encodeGeohash(lon, lat, 3);
  const h5 = encodeGeohash(lon, lat, 5);
  const h7 = encodeGeohash(lon, lat, 7);
  assert.ok(h5.startsWith(h3));
  assert.ok(h7.startsWith(h5));
});

test("encodeGeohash: clamps out-of-range / antimeridian / poles without exploding", () => {
  assert.equal(encodeGeohash(180, 90, 3).length, 3);
  assert.equal(encodeGeohash(-180, -90, 3).length, 3);
  assert.equal(encodeGeohash(999, 999, 4).length, 4); // clamped to 180/90
  assert.equal(encodeGeohash(-999, -999, 4).length, 4);
  // Clamped extremes equal the in-range extreme.
  assert.equal(encodeGeohash(999, 999, 5), encodeGeohash(180, 90, 5));
});

test("cellSizeDegrees: precision raises resolution (smaller cells)", () => {
  const p1 = cellSizeDegrees(1);
  const p3 = cellSizeDegrees(3);
  const p5 = cellSizeDegrees(5);
  assert.deepEqual(p1, { lonStep: 45, latStep: 45 });
  // p3 ~ 1.40625 deg (~150km), the ticket's target cell size.
  assert.ok(Math.abs(p3.lonStep - 1.40625) < 1e-9);
  assert.ok(Math.abs(p3.latStep - 1.40625) < 1e-9);
  assert.ok(p5.lonStep < p3.lonStep && p3.lonStep < p1.lonStep);
});

test("viewportCells: covers all four corners of a small bbox", () => {
  const bbox = { w: -1.2, s: 51.2, e: 0.9, n: 52.4 };
  const precision = 4;
  const { cells, bounded } = viewportCells(bbox, precision);
  assert.equal(bounded, true);
  const corners = [
    encodeGeohash(bbox.w, bbox.s, precision),
    encodeGeohash(bbox.e, bbox.s, precision),
    encodeGeohash(bbox.w, bbox.n, precision),
    encodeGeohash(bbox.e, bbox.n, precision),
  ];
  for (const c of corners) assert.ok(cells.includes(c), `missing corner cell ${c}`);
});

test("viewportCells: also covers the cell of an interior point", () => {
  const bbox = { w: 10, s: 40, e: 16, n: 46 };
  const precision = 3;
  const { cells } = viewportCells(bbox, precision);
  const interior = encodeGeohash(13, 43, precision);
  assert.ok(cells.includes(interior));
});

test("viewportCells: result is deduplicated and sorted", () => {
  const { cells } = viewportCells({ w: 0, s: 0, e: 5, n: 5 }, 3);
  const unique = [...new Set(cells)];
  assert.equal(cells.length, unique.length); // no dupes
  assert.deepEqual(cells, [...cells].sort()); // sorted
});

test("viewportCells: a tiny bbox maps to a single cell", () => {
  const { cells, bounded } = viewportCells({ w: 13.0, s: 52.0, e: 13.001, n: 52.001 }, 3);
  assert.equal(bounded, true);
  assert.equal(cells.length, 1);
  assert.equal(cells[0], encodeGeohash(13.0005, 52.0005, 3));
});

test("viewportCells: a world bbox at fine precision is reported UNbounded (fall back to global)", () => {
  const { cells, bounded } = viewportCells({ w: -180, s: -90, e: 180, n: 90 }, 3);
  assert.equal(bounded, false);
  assert.equal(cells.length, 0);
});

test("viewportCells: cover stays within the hard cap when bounded", () => {
  // Choose a bbox + precision that is bounded; assert we never exceed the cap.
  const { cells, bounded } = viewportCells({ w: 0, s: 0, e: 20, n: 20 }, 3);
  assert.equal(bounded, true);
  assert.ok(cells.length <= MAX_VIEWPORT_CELLS);
});

test("viewportCells: antimeridian-edge bbox does not explode", () => {
  // Near the antimeridian (clamped range, so w<e enforced upstream). Just assert it terminates and
  // returns a bounded, non-empty, deterministic cover.
  const { cells, bounded } = viewportCells({ w: 178, s: -5, e: 180, n: 5 }, 3);
  assert.equal(bounded, true);
  assert.ok(cells.length >= 1);
  assert.deepEqual(cells, [...cells].sort());
});

test("viewportCells: polar bbox does not explode", () => {
  const { cells, bounded } = viewportCells({ w: -10, s: 85, e: 10, n: 90 }, 3);
  assert.equal(bounded, true);
  assert.ok(cells.length >= 1);
});

test("geoChannel: names the per-cell channel", () => {
  assert.equal(geoChannel("u10"), "live:geo:u10");
  assert.equal(geoChannel("gcpvj0"), "live:geo:gcpvj0");
});
