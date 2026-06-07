import test from "node:test";
import assert from "node:assert/strict";
import { buildReconInsert, type ReconWindowRow } from "../src/repositories/recon.js";

const sample = (over: Partial<ReconWindowRow> = {}): ReconWindowRow => ({
  norad_id: 40115,
  aoi_id: "aoi-strait",
  sensor_type: "optical",
  t_ingress: 1000,
  t_peak: 1100,
  t_egress: 1200,
  min_distance_km: 12.5,
  sunlit_at_peak: true,
  quality: 0.92,
  ...over,
});

test("recon insert: columns, conflict target, and to_timestamp on time columns", () => {
  const { sql } = buildReconInsert([sample()]);
  assert.match(
    sql,
    /INSERT INTO recon_windows \(norad_id, aoi_id, sensor_type, t_ingress, t_peak, t_egress, min_distance_km, sunlit_at_peak, quality\)/,
  );
  assert.match(sql, /ON CONFLICT \(norad_id, aoi_id, t_ingress\) DO NOTHING$/);
  // The three time columns are wrapped in to_timestamp(...).
  assert.match(sql, /to_timestamp\(\$4\), to_timestamp\(\$5\), to_timestamp\(\$6\)/);
});

test("recon insert: single-row param order and values", () => {
  const { params } = buildReconInsert([sample()]);
  assert.deepEqual(params, [40115, "aoi-strait", "optical", 1000, 1100, 1200, 12.5, true, 0.92]);
});

test("recon insert: placeholders renumber across rows ($1..$18)", () => {
  const rows = [sample(), sample({ norad_id: 25544, aoi_id: "aoi-b", sunlit_at_peak: false })];
  const { sql, params } = buildReconInsert(rows);
  assert.equal(params.length, 18); // 9 per row × 2
  assert.match(sql, /VALUES \(.+\), \(.+\)/);
  // First row uses $1..$9, second row $10..$18 with to_timestamp wrappers preserved.
  assert.match(sql, /to_timestamp\(\$13\), to_timestamp\(\$14\), to_timestamp\(\$15\)/);
  assert.match(sql, /\$18\)/);
});

test("recon insert: second row's params follow the first in order", () => {
  const rows = [sample(), sample({ norad_id: 25544, aoi_id: "aoi-b", sunlit_at_peak: false, quality: 0.4 })];
  const { params } = buildReconInsert(rows);
  // Row 2 starts at index 9.
  assert.equal(params[9], 25544);
  assert.equal(params[10], "aoi-b");
  assert.equal(params[15], 12.5); // min_distance_km carried over from default
  assert.equal(params[16], false); // sunlit_at_peak
  assert.equal(params[17], 0.4); // row 2 quality
  assert.equal(params[8], 0.92); // row 1 quality
});
