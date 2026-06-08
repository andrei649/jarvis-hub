// Seed Redis live-state so the dashboard's LIVE mode shows data without running Kafka/workers.
// Writes `live:<layer>:<id>` envelopes + `geo:<layer>` members in the same shape the live-writer
// uses, so the /live snapshot returns them. Demo keys are written WITHOUT a TTL so they persist.
//
//   REDIS_URL=redis://localhost:6379 node scripts/seed-live.mjs   (or: npm run seed:live)

import Redis from "ioredis";

const redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379");
const now = Date.now() / 1000;

// A small Strait of Hormuz live snapshot across the point layers.
const entities = {
  adsb: [
    { id: "4ca7b3", lon: 56.2, lat: 26.5, payload: { callsign: "UAE201", gs_kt: 451, alt_m: 9500, is_military: false } },
    { id: "43c6db", lon: 56.45, lat: 26.95, payload: { callsign: "RCH471", gs_kt: 420, alt_m: 11000, is_military: true } },
  ],
  ais: [
    { id: "636092297", lon: 56.6, lat: 26.5, payload: { mmsi: 636092297, sog_kt: 12, cog_deg: 290 } },
    { id: "412331100", lon: 56.4, lat: 26.57, payload: { mmsi: 412331100, sog_kt: 0, cog_deg: 110 } },
  ],
  tle: [
    { id: "40115", lon: 56.0, lat: 26.0, payload: { norad_id: 40115, sensor_type: "sar", velocity_kms: 7.5, is_sunlit: true } },
  ],
  context: [
    { id: "dark:412331100", lon: 56.42, lat: 26.56, payload: { kind: "dark_vessel", mmsi: 412331100, gap_seconds: 180, status: "dark" } },
  ],
};

let count = 0;
for (const [layer, list] of Object.entries(entities)) {
  for (const e of list) {
    const env = { domain: layer, entity_id: e.id, ts: now, lon: e.lon, lat: e.lat, payload: e.payload };
    await redis.set(`live:${layer}:${e.id}`, JSON.stringify(env)); // no TTL: persistent demo state
    await redis.geoadd(`geo:${layer}`, e.lon, e.lat, e.id);
    count += 1;
  }
}

console.log(`seeded ${count} live entities across ${Object.keys(entities).length} layers`);
await redis.quit();
