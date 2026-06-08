// WorldView :: demo-feed.mjs — an always-on SYNTHETIC live feed. No API keys, no Kafka, no workers.
//
// Keeps the globe alive: every tick it MOVES a small, bounded cast (≈8 aircraft, 6 vessels,
// 3 satellites, + a dark vessel and a GPS-jamming cell) near the Strait of Hormuz and writes the
// live snapshot to Redis in the EXACT shape the live-writer uses — `live:<layer>:<id>` envelopes,
// `geo:<layer>` members, and `chan:<layer>` / `live:geo:<cell>` pub/sub deltas — so the `/live`
// WebSocket serves them immediately (snapshot on connect + deltas while connected). Every few
// seconds it also INSERTs history rows into TimescaleDB (adsb_positions / ais_positions /
// satellite_ephemeris / gps_jamming) so scrubbing the 24h timeline shows recent trails.
//
// Honest + safe: reads DATABASE_URL / REDIS_URL from env (same defaults as seed-live & the API);
// clean shutdown on SIGINT/SIGTERM; bounded volume (history is pruned to a rolling window); never
// crashes if Redis/Postgres is momentarily unavailable (it retries/skips that tick).
//
//   REDIS_URL=redis://localhost:6379 DATABASE_URL=postgres://… node scripts/demo-feed.mjs
//   (or: npm run demo:feed)
//
// Tunables (env): DEMO_TICK_MS (live cadence, default 1000), DEMO_HISTORY_EVERY_MS (default 5000),
// DEMO_HISTORY_RETENTION_MIN (rolling history window kept per entity, default 30),
// DEMO_NO_HISTORY=1 (Redis-only, skip Postgres entirely).

import Redis from "ioredis";
import pg from "pg";

const { Pool } = pg;

// --- Config -----------------------------------------------------------------
const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const DATABASE_URL =
  process.env.DATABASE_URL ?? "postgres://worldview:worldview@localhost:5432/worldview";
const TICK_MS = Number(process.env.DEMO_TICK_MS ?? 1000); // live snapshot cadence (≈1 Hz)
const HISTORY_EVERY_MS = Number(process.env.DEMO_HISTORY_EVERY_MS ?? 5000); // history insert cadence
const HISTORY_RETENTION_MIN = Number(process.env.DEMO_HISTORY_RETENTION_MIN ?? 30); // rolling window
const NO_HISTORY = process.env.DEMO_NO_HISTORY === "1";
const GEOHASH_PRECISION = Number(process.env.WS_GEOHASH_PRECISION ?? 3); // mirror the API default

// Live Redis TTLs per layer — same as the live-writer (backend-api/src/types.ts LIVE_TTL_SECONDS),
// so an entity that stops updating drops off the globe on its own. The feed rewrites every tick,
// well inside these windows. `context` has no TTL (persistent), matching the API.
const LIVE_TTL_SECONDS = { adsb: 60, ais: 600, tle: 120, ew: 600 };

// --- Reference cast — anchored to the demo.sql Strait of Hormuz scenario ----
// Aircraft (ADS-B). Each moves along a heading; one flies a military holding orbit. icao24 hex ids.
const AIRCRAFT = [
  { id: "4ca7b3", lon: 55.80, lat: 26.30, alt_m: 9500, gs_kt: 451, track_deg: 95, callsign: "UAE201", is_military: false },
  { id: "43c6db", lon: 56.40, lat: 26.90, alt_m: 11000, gs_kt: 420, track_deg: 270, callsign: "RCH471", is_military: true, orbit: { cx: 56.40, cy: 26.90, r: 0.10 } },
  { id: "738a11", lon: 56.10, lat: 26.10, alt_m: 10600, gs_kt: 465, track_deg: 60, callsign: "QTR8", is_military: false },
  { id: "76cd01", lon: 56.90, lat: 26.80, alt_m: 9200, gs_kt: 438, track_deg: 250, callsign: "SVA77", is_military: false },
  { id: "06a0f2", lon: 56.30, lat: 27.05, alt_m: 11600, gs_kt: 410, track_deg: 130, callsign: "ABY55", is_military: false },
  { id: "8961ab", lon: 55.95, lat: 26.95, alt_m: 8800, gs_kt: 470, track_deg: 110, callsign: "IGO61", is_military: false },
  { id: "ae1f23", lon: 56.55, lat: 25.95, alt_m: 12000, gs_kt: 395, track_deg: 20, callsign: "TOPGUN", is_military: true },
  { id: "44ce19", lon: 56.70, lat: 26.40, alt_m: 9900, gs_kt: 455, track_deg: 300, callsign: "DLH4", is_military: false },
];

// Vessels (AIS). Slower; one is the "dark" tanker shadowed by a context dark-vessel marker.
const VESSELS = [
  { id: "636092297", lon: 56.80, lat: 26.50, sog_kt: 12, cog_deg: 290, name: "EVER ELYSIUM" },
  { id: "412331100", lon: 56.30, lat: 26.60, sog_kt: 10, cog_deg: 110, name: "DARK STAR", dark: true },
  { id: "538005102", lon: 56.55, lat: 26.30, sog_kt: 14, cog_deg: 75, name: "PACIFIC GEM" },
  { id: "356092000", lon: 56.20, lat: 26.85, sog_kt: 9, cog_deg: 200, name: "GULF TRADER" },
  { id: "477123400", lon: 56.95, lat: 26.65, sog_kt: 11, cog_deg: 250, name: "HORMUZ STAR" },
  { id: "240183000", lon: 56.05, lat: 26.45, sog_kt: 0, cog_deg: 0, name: "AT ANCHOR" }, // anchored
];

// Satellites (sub-satellite point sweeping a ground track — a simple moving sub-point, not SGP4).
const SATELLITES = [
  { id: "40115", lon: 54.0, lat: 24.0, alt_m: 500000, velocity_kms: 7.5, sensor_type: "sar", dLon: 0.012, dLat: 0.009 },
  { id: "33591", lon: 55.5, lat: 27.5, alt_m: 705000, velocity_kms: 7.4, sensor_type: "optical", dLon: -0.010, dLat: -0.011 },
  { id: "43013", lon: 53.0, lat: 25.0, alt_m: 620000, velocity_kms: 7.6, sensor_type: "sigint", dLon: 0.014, dLat: -0.006 },
];

// GPS-jamming cell (EW) — a single H3-ish hex polygon whose intensity slowly pulses.
const JAMMING = {
  id: "85283473fffffff",
  h3_resolution: 5,
  // Hex polygon (WKT) centered on the strait; matches the demo.sql cell footprint.
  wkt: "POLYGON((56.50 26.60,56.62 26.60,56.68 26.68,56.62 26.76,56.50 26.76,56.44 26.68,56.50 26.60))",
  lon: 56.56, // representative center for the live point/geo member
  lat: 26.68,
};

// Watch box — keep everyone inside the Strait of Hormuz AOI; bounce off the edges so motion is
// continuous and bounded forever (no drift off-globe).
const BBOX = { w: 55.6, s: 25.8, e: 57.2, n: 27.0 };

// --- Small geohash encoder (mirrors backend-api/src/live/geohash.ts) --------
// Lets deltas reach bbox-scoped /live clients on `live:geo:<cell>` channels in addition to the
// global `chan:<layer>` channel. Self-contained so this script has no TS-build dependency.
const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";
function encodeGeohash(lon, lat, precision) {
  const p = Math.max(1, Math.floor(precision));
  let latMin = -90, latMax = 90, lonMin = -180, lonMax = 180;
  let clon = Math.min(180, Math.max(-180, lon));
  let clat = Math.min(90, Math.max(-90, lat));
  let hash = "", bits = 0, bitCount = 0, evenBit = true;
  while (hash.length < p) {
    if (evenBit) {
      const mid = (lonMin + lonMax) / 2;
      if (clon >= mid) { bits = (bits << 1) | 1; lonMin = mid; } else { bits = bits << 1; lonMax = mid; }
    } else {
      const mid = (latMin + latMax) / 2;
      if (clat >= mid) { bits = (bits << 1) | 1; latMin = mid; } else { bits = bits << 1; latMax = mid; }
    }
    evenBit = !evenBit;
    if (++bitCount === 5) { hash += BASE32[bits]; bits = 0; bitCount = 0; }
  }
  return hash;
}

// --- Motion helpers ---------------------------------------------------------
const KT_TO_DEG_PER_S = 1 / (60 * 3600); // 1 knot ≈ 1 nm/h; 1 nm ≈ 1/60 deg → deg/s

function bounce(v, lo, hi, headingRef, axis) {
  // Reflect a coordinate off the AOI edges and flip the heading component so motion reverses.
  if (v < lo) { headingRef[axis] = -headingRef[axis]; return lo + (lo - v); }
  if (v > hi) { headingRef[axis] = -headingRef[axis]; return hi - (v - hi); }
  return v;
}

function stepAircraft(a, dt) {
  if (a.orbit) {
    // Military holding orbit: advance angle around a fixed center.
    a.theta = (a.theta ?? 0) + 0.25 * dt; // rad/s
    a.lon = a.orbit.cx + a.orbit.r * Math.cos(a.theta);
    a.lat = a.orbit.cy + a.orbit.r * Math.sin(a.theta) * 0.9;
    a.track_deg = ((a.theta * 180) / Math.PI + 90) % 360;
    a.alt_m += Math.sin(a.theta) * 5; // gentle altitude wobble
    return;
  }
  const speedDeg = a.gs_kt * KT_TO_DEG_PER_S * dt;
  const rad = (a.track_deg * Math.PI) / 180;
  // track_deg is compass bearing (0=N, 90=E): dLon ~ sin(bearing), dLat ~ cos(bearing).
  const h = { lon: Math.sin(rad), lat: Math.cos(rad) };
  let nl = a.lon + speedDeg * h.lon;
  let nt = a.lat + speedDeg * h.lat;
  nl = bounce(nl, BBOX.w, BBOX.e, h, "lon");
  nt = bounce(nt, BBOX.s, BBOX.n, h, "lat");
  a.lon = nl;
  a.lat = nt;
  a.track_deg = (Math.atan2(h.lon, h.lat) * 180) / Math.PI;
  if (a.track_deg < 0) a.track_deg += 360;
  a.alt_m += Math.sin(Date.now() / 60000 + a.lon) * 8; // slow climb/descent
}

function stepVessel(v, dt) {
  if (v.sog_kt <= 0) return; // anchored
  const speedDeg = v.sog_kt * KT_TO_DEG_PER_S * dt;
  const rad = (v.cog_deg * Math.PI) / 180;
  const h = { lon: Math.sin(rad), lat: Math.cos(rad) };
  let nl = v.lon + speedDeg * h.lon;
  let nt = v.lat + speedDeg * h.lat;
  nl = bounce(nl, BBOX.w, BBOX.e, h, "lon");
  nt = bounce(nt, BBOX.s, BBOX.n, h, "lat");
  v.lon = nl;
  v.lat = nt;
  v.cog_deg = (Math.atan2(h.lon, h.lat) * 180) / Math.PI;
  if (v.cog_deg < 0) v.cog_deg += 360;
}

function stepSatellite(s, dt) {
  s.lon += s.dLon * dt;
  s.lat += s.dLat * dt;
  // Wrap longitude; reflect latitude so the ground track sweeps back and forth over the AOI.
  if (s.lon > 60) s.lon = 50;
  if (s.lon < 50) s.lon = 60;
  if (s.lat > 30 || s.lat < 20) s.dLat = -s.dLat;
}

// --- Redis live write (same envelope/keys as seed-live.mjs & the live-writer) ----
function envelope(domain, id, lon, lat, ts, payload) {
  return { domain, entity_id: id, ts, lon, lat, payload };
}

async function writeLive(redis, domain, id, lon, lat, ts, payload) {
  const env = envelope(domain, id, lon, lat, ts, payload);
  const json = JSON.stringify(env);
  const ttl = LIVE_TTL_SECONDS[domain]; // undefined for `context` → persistent (no TTL)
  const tx = redis.multi();
  if (ttl) tx.set(`live:${domain}:${id}`, json, "EX", ttl);
  else tx.set(`live:${domain}:${id}`, json);
  tx.geoadd(`geo:${domain}`, lon, lat, id);
  // Deltas: global per-layer channel (no-bbox clients) + geohash cell (bbox-scoped clients).
  tx.publish(`chan:${domain}`, json);
  if (GEOHASH_PRECISION > 0) {
    tx.publish(`live:geo:${encodeGeohash(lon, lat, GEOHASH_PRECISION)}`, json);
  }
  await tx.exec();
}

async function tickLive(redis) {
  const dt = TICK_MS / 1000;
  const ts = Date.now() / 1000; // seconds, like seed-live & the live-writer
  let n = 0;

  for (const a of AIRCRAFT) {
    stepAircraft(a, dt);
    await writeLive(redis, "adsb", a.id, a.lon, a.lat, ts, {
      callsign: a.callsign,
      gs_kt: Math.round(a.gs_kt),
      alt_m: Math.round(a.alt_m),
      track_deg: Math.round(a.track_deg),
      is_military: a.is_military,
      on_ground: false,
      source: "demo",
    });
    n++;
  }

  for (const v of VESSELS) {
    stepVessel(v, dt);
    await writeLive(redis, "ais", v.id, v.lon, v.lat, ts, {
      mmsi: Number(v.id),
      name: v.name,
      sog_kt: v.sog_kt,
      cog_deg: Math.round(v.cog_deg),
      heading_deg: Math.round(v.cog_deg),
      nav_status: v.sog_kt > 0 ? 0 : 1,
      source: "demo",
    });
    n++;
    // Shadow the "dark" tanker with a context dark-vessel marker that trails its last position.
    if (v.dark) {
      await writeLive(redis, "context", `dark:${v.id}`, v.lon + 0.02, v.lat - 0.01, ts, {
        kind: "dark_vessel",
        mmsi: Number(v.id),
        gap_seconds: 180,
        status: "dark",
      });
      n++;
    }
  }

  for (const s of SATELLITES) {
    stepSatellite(s, dt);
    await writeLive(redis, "tle", s.id, s.lon, s.lat, ts, {
      norad_id: Number(s.id),
      sensor_type: s.sensor_type,
      velocity_kms: s.velocity_kms,
      alt_m: s.alt_m,
      is_sunlit: s.sensor_type === "optical",
    });
    n++;
  }

  // EW jamming cell — intensity pulses between ~0.3 and ~1.0.
  const intensity = 0.65 + 0.35 * Math.sin(Date.now() / 8000);
  await writeLive(redis, "ew", JAMMING.id, JAMMING.lon, JAMMING.lat, ts, {
    h3_index: JAMMING.id,
    h3_resolution: JAMMING.h3_resolution,
    intensity: Number(intensity.toFixed(2)),
    sample_count: 10,
    source: "demo",
  });
  n++;

  return n;
}

// --- History writes (match backend-api/src/repositories/historyWriter.ts) ----
async function tickHistory(pool) {
  const ts = Date.now() / 1000;
  let written = 0;

  // ADS-B → adsb_positions (PointZ with altitude). ON CONFLICT keeps it idempotent on (icao24, ts).
  for (const a of AIRCRAFT) {
    const r = await pool.query(
      `INSERT INTO adsb_positions (ts, icao24, geom, alt_m, gs_kt, track_deg, on_ground, is_military, source)
       VALUES (to_timestamp($1), $2, ST_SetSRID(ST_MakePoint($3,$4,$5),4326), $6,$7,$8,$9,$10,'demo')
       ON CONFLICT (icao24, ts) DO NOTHING`,
      [ts, a.id, a.lon, a.lat, Math.round(a.alt_m), Math.round(a.alt_m), Math.round(a.gs_kt), Math.round(a.track_deg), false, a.is_military],
    );
    written += r.rowCount ?? 0;
  }

  // AIS → ais_positions (2D Point). PK (mmsi, ts).
  for (const v of VESSELS) {
    const r = await pool.query(
      `INSERT INTO ais_positions (ts, mmsi, geom, sog_kt, cog_deg, heading_deg, nav_status, source)
       VALUES (to_timestamp($1), $2, ST_SetSRID(ST_MakePoint($3,$4),4326), $5,$6,$7,$8,'demo')
       ON CONFLICT (mmsi, ts) DO NOTHING`,
      [ts, Number(v.id), v.lon, v.lat, v.sog_kt, Math.round(v.cog_deg), Math.round(v.cog_deg), v.sog_kt > 0 ? 0 : 1],
    );
    written += r.rowCount ?? 0;
  }

  // Satellites → satellite_ephemeris (PointZ + buffered ground footprint). PK (norad_id, ts).
  for (const s of SATELLITES) {
    const r = await pool.query(
      `INSERT INTO satellite_ephemeris (ts, norad_id, geom, velocity_kms, sensor_type, footprint, is_sunlit, source)
       VALUES (to_timestamp($1), $2, ST_SetSRID(ST_MakePoint($3,$4,$5),4326), $6, $7,
               ST_Buffer(ST_SetSRID(ST_MakePoint($3,$4),4326), 0.3), $8, 'demo')
       ON CONFLICT (norad_id, ts) DO NOTHING`,
      [ts, Number(s.id), s.lon, s.lat, s.alt_m, s.velocity_kms, s.sensor_type, s.sensor_type === "optical"],
    );
    written += r.rowCount ?? 0;
  }

  // EW → gps_jamming (H3 hex polygon). PK (h3_index, ts).
  const intensity = Number((0.65 + 0.35 * Math.sin(Date.now() / 8000)).toFixed(2));
  {
    const r = await pool.query(
      `INSERT INTO gps_jamming (ts, h3_index, h3_resolution, h3_geom, intensity, sample_count, source)
       VALUES (to_timestamp($1), $2, $3, ST_SetSRID(ST_GeomFromText($4),4326), $5, $6, 'demo')
       ON CONFLICT (h3_index, ts) DO NOTHING`,
      [ts, JAMMING.id, JAMMING.h3_resolution, JAMMING.wkt, intensity, 10],
    );
    written += r.rowCount ?? 0;
  }

  return written;
}

// Keep history bounded: prune demo rows older than the rolling retention window.
async function pruneHistory(pool) {
  const cutoff = `${HISTORY_RETENTION_MIN} minutes`;
  const tables = ["adsb_positions", "ais_positions", "satellite_ephemeris", "gps_jamming"];
  for (const t of tables) {
    try {
      await pool.query(`DELETE FROM ${t} WHERE source = 'demo' AND ts < now() - $1::interval`, [cutoff]);
    } catch {
      // Pruning is best-effort; a transient error must never stop the feed.
    }
  }
}

// --- Lifecycle --------------------------------------------------------------
let running = true;
let redis = null;
let pool = null;

function log(...args) {
  console.log(new Date().toISOString(), "[demo-feed]", ...args);
}

async function main() {
  log(`starting — live every ${TICK_MS}ms, history every ${HISTORY_EVERY_MS}ms` + (NO_HISTORY ? " (history disabled)" : ""));
  log(`REDIS_URL=${REDIS_URL}` + (NO_HISTORY ? "" : `  DATABASE_URL=${DATABASE_URL.replace(/:\/\/[^@]*@/, "://***@")}`));

  // ioredis reconnects on its own; don't crash on transient errors.
  redis = new Redis(REDIS_URL, { lazyConnect: false, maxRetriesPerRequest: 2 });
  redis.on("error", (err) => log("redis error:", err.message));

  if (!NO_HISTORY) {
    pool = new Pool({ connectionString: DATABASE_URL, max: 2 });
    pool.on("error", (err) => log("pg pool error:", err.message));
  }

  let liveTicks = 0;
  let historyRows = 0;
  let lastHistory = 0;
  let lastPrune = 0;

  // Live loop — its own timer so a slow history write never stalls the globe.
  const liveTimer = setInterval(async () => {
    if (!running) return;
    try {
      const n = await tickLive(redis);
      liveTicks++;
      if (liveTicks % 30 === 0) log(`live ok — ${n} entities/tick, ${liveTicks} ticks, ${historyRows} history rows so far`);
    } catch (err) {
      log("live tick skipped:", err.message); // retry next tick
    }
  }, TICK_MS);

  // History loop — lower cadence, bounded, idempotent.
  const historyTimer = NO_HISTORY
    ? null
    : setInterval(async () => {
        if (!running) return;
        const now = Date.now();
        if (now - lastHistory < HISTORY_EVERY_MS) return;
        lastHistory = now;
        try {
          const w = await tickHistory(pool);
          historyRows += w;
          // Prune roughly once a minute to keep the window bounded.
          if (now - lastPrune > 60000) {
            lastPrune = now;
            await pruneHistory(pool);
          }
        } catch (err) {
          log("history tick skipped:", err.message); // DB momentarily down → skip, retry later
        }
      }, HISTORY_EVERY_MS);

  const shutdown = async (sig) => {
    if (!running) return;
    running = false;
    log(`${sig} — shutting down…`);
    clearInterval(liveTimer);
    if (historyTimer) clearInterval(historyTimer);
    try { if (redis) await redis.quit(); } catch { /* ignore */ }
    try { if (pool) await pool.end(); } catch { /* ignore */ }
    log("bye");
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}

main().catch((err) => {
  console.error("[demo-feed] fatal:", err);
  process.exit(1);
});
