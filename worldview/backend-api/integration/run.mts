// Integration tests — exercise the repositories against a REAL TimescaleDB + Redis (see the
// `integration` job in .github/workflows/worldview.yml). Unlike the unit tests, this validates
// the actual hypertables, continuous aggregates, PostGIS geometry, and the live Redis path.
//
//   DATABASE_URL=... REDIS_URL=... npx tsx integration/run.mts
// Expects the schema applied, demo seed loaded, caggs refreshed, and live-state seeded.

import { getPool } from "../src/plugins/db.js";
import { getRedis } from "../src/plugins/redis.js";
import {
  flightsAsOf,
  vesselsAsOf,
  satellitesAsOf,
  jammingAsOf,
  contextAsOf,
  trackOf,
} from "../src/repositories/history.js";
import { liveSnapshot } from "../src/repositories/live.js";

let failures = 0;
function check(name: string, ok: boolean, detail: unknown = "") {
  const status = ok ? "ok  " : "FAIL";
  console.log(`${status} ${name} ${detail === "" ? "" : `-> ${JSON.stringify(detail)}`}`);
  if (!ok) failures += 1;
}

const pool = getPool();
const redis = getRedis();
const now = Date.now() / 1000;

// --- Historical (real TimescaleDB hypertables + PostGIS) ---
const flightsRaw = await flightsAsOf(pool, now, null, "raw");
check("flightsAsOf raw returns seeded aircraft", flightsRaw.features.length >= 2, flightsRaw.features.length);
check(
  "military flag present on a flight",
  flightsRaw.features.some((f) => f.properties.is_military === true),
);

// Real continuous-aggregate path (requires the caggs to be refreshed in CI).
const flightsMin = await flightsAsOf(pool, now, null, "minute");
check("flightsAsOf minute (continuous aggregate) returns rows", flightsMin.features.length >= 1, flightsMin.features.length);

const vessels = await vesselsAsOf(pool, now, null, "raw");
check("vesselsAsOf returns seeded vessels", vessels.features.length >= 2, vessels.features.length);

const sats = await satellitesAsOf(pool, now, null);
check("satellitesAsOf returns a satellite with a footprint", sats.features.some((f) => !!f.properties.footprint));

const jam = await jammingAsOf(pool, now, null);
check("jammingAsOf returns H3 cells", jam.features.length >= 1, jam.features.length);

const ctx = await contextAsOf(pool, now, null);
const kinds = new Set(ctx.features.map((f) => f.properties.kind));
check("contextAsOf returns notam + event + dark_vessel", kinds.has("notam") && kinds.has("event") && kinds.has("dark_vessel"), [...kinds]);

const track = await trackOf(pool, "adsb", "4ca7b3", now - 3600, now);
const trackFeat = track.features[0];
check(
  "trackOf returns a multi-point LineString",
  !!trackFeat && (trackFeat.geometry as { type: string }).type === "LineString" && Number(trackFeat.properties.count) > 2,
  trackFeat?.properties.count,
);

// --- Live (real Redis) ---
const liveAdsb = await liveSnapshot(redis, "adsb");
check("liveSnapshot adsb returns seeded live entities", liveAdsb.features.length >= 1, liveAdsb.features.length);

await pool.end();
await redis.quit();

console.log(`\n${failures === 0 ? "PASS" : "FAIL"} — ${failures} failing check(s)`);
process.exit(failures === 0 ? 0 : 1);
