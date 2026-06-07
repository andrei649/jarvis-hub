import test from "node:test";
import assert from "node:assert/strict";
import { reconMessageToRow } from "../src/consumers/reconWriter.js";
import type { ReconWindowRow } from "../src/repositories/recon.js";

const validMsg = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  schema: "worldview.recon.v1",
  norad_id: 40115,
  aoi_id: "aoi-strait",
  sensor_type: "optical",
  t_ingress: 1717795200.5,
  t_peak: 1717795260.25,
  t_egress: 1717795320,
  min_distance_km: 12.5,
  sunlit_at_peak: true,
  quality: 0.92,
  ...over,
});

test("reconMessageToRow: a valid contract message maps to the right ReconWindowRow", () => {
  const row = reconMessageToRow(validMsg());
  const expected: ReconWindowRow = {
    norad_id: 40115,
    aoi_id: "aoi-strait",
    sensor_type: "optical",
    t_ingress: 1717795200.5,
    t_peak: 1717795260.25,
    t_egress: 1717795320,
    min_distance_km: 12.5,
    sunlit_at_peak: true,
    quality: 0.92,
  };
  assert.deepEqual(row, expected);
  // Extra/unknown fields on the message (e.g. `schema`) are ignored, not copied through.
  assert.deepEqual(Object.keys(row ?? {}).sort(), Object.keys(expected).sort());
});

test("reconMessageToRow: sunlit_at_peak boolean is preserved (false stays false)", () => {
  const row = reconMessageToRow(validMsg({ sunlit_at_peak: false }));
  assert.equal(row?.sunlit_at_peak, false);
  assert.equal(typeof row?.sunlit_at_peak, "boolean");
});

test("reconMessageToRow: numeric fields keep their numeric type and float values", () => {
  const row = reconMessageToRow(validMsg({ norad_id: 25544, quality: 0, min_distance_km: 0.0 }));
  assert.equal(typeof row?.norad_id, "number");
  assert.equal(row?.norad_id, 25544);
  assert.equal(typeof row?.quality, "number");
  assert.equal(row?.quality, 0); // 0 is a valid finite number, not rejected
  assert.equal(row?.min_distance_km, 0);
  assert.equal(typeof row?.t_peak, "number");
});

test("reconMessageToRow: non-object input returns null", () => {
  assert.equal(reconMessageToRow(null), null);
  assert.equal(reconMessageToRow(undefined), null);
  assert.equal(reconMessageToRow(42), null);
  assert.equal(reconMessageToRow("recon"), null);
  assert.equal(reconMessageToRow(true), null);
});

test("reconMessageToRow: each missing required field yields null", () => {
  const required = [
    "norad_id",
    "aoi_id",
    "sensor_type",
    "t_ingress",
    "t_peak",
    "t_egress",
    "min_distance_km",
    "sunlit_at_peak",
    "quality",
  ];
  for (const field of required) {
    const msg = validMsg();
    delete msg[field];
    assert.equal(reconMessageToRow(msg), null, `missing ${field} should map to null`);
  }
});

test("reconMessageToRow: wrong-typed fields yield null", () => {
  assert.equal(reconMessageToRow(validMsg({ norad_id: "40115" })), null); // string, not number
  assert.equal(reconMessageToRow(validMsg({ aoi_id: 123 })), null); // number, not string
  assert.equal(reconMessageToRow(validMsg({ sensor_type: null })), null); // null, not string
  assert.equal(reconMessageToRow(validMsg({ t_ingress: "1000" })), null); // string, not number
  assert.equal(reconMessageToRow(validMsg({ min_distance_km: null })), null);
  assert.equal(reconMessageToRow(validMsg({ sunlit_at_peak: "true" })), null); // string, not bool
  assert.equal(reconMessageToRow(validMsg({ sunlit_at_peak: 1 })), null); // number, not bool
  assert.equal(reconMessageToRow(validMsg({ quality: "0.9" })), null);
});

test("reconMessageToRow: non-finite numbers (NaN/Infinity) are rejected", () => {
  assert.equal(reconMessageToRow(validMsg({ quality: NaN })), null);
  assert.equal(reconMessageToRow(validMsg({ t_peak: Infinity })), null);
  assert.equal(reconMessageToRow(validMsg({ norad_id: -Infinity })), null);
});
