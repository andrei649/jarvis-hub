import test from "node:test";
import assert from "node:assert/strict";
import { deltaChannels, writeLive } from "../src/repositories/live.js";
import { encodeGeohash, geoChannel } from "../src/live/geohash.js";
import { planSubscription } from "../src/live/subscription.js";
import { channel } from "../src/repositories/live.js";
import type { BBox, Layer } from "../src/types.js";

// --- deltaChannels (pure publish fan-out) ---

test("deltaChannels: publishes to the global layer channel AND the geohash cell channel", () => {
  const lon = 13.404954;
  const lat = 52.520008; // Berlin
  const chans = deltaChannels("adsb", lon, lat, 3);
  assert.deepEqual(chans, [channel("adsb"), geoChannel(encodeGeohash(lon, lat, 3))]);
  assert.equal(chans[1], `live:geo:${encodeGeohash(lon, lat, 3)}`);
});

test("deltaChannels: precision 0 disables sharding (global channel only)", () => {
  const chans = deltaChannels("ais", 1, 2, 0);
  assert.deepEqual(chans, [channel("ais")]);
});

test("deltaChannels: a null position publishes only to the global channel", () => {
  assert.deepEqual(deltaChannels("ew", null, null, 3), [channel("ew")]);
  assert.deepEqual(deltaChannels("ew", 5, null, 3), [channel("ew")]);
});

test("deltaChannels: two entities in different cells get different geo channels", () => {
  const a = deltaChannels("adsb", 13.4, 52.5, 3)[1]; // Berlin
  const b = deltaChannels("adsb", -0.12, 51.5, 3)[1]; // London
  assert.notEqual(a, b);
});

// --- writeLive publish fan-out against a mock Redis multi() pipeline ---

interface Published {
  channel: string;
  payload: string;
}

function mockRedis() {
  const published: Published[] = [];
  const geoadds: Array<{ key: string; lon: number; lat: number; member: string }> = [];
  const sets: Array<{ key: string; value: string }> = [];
  const tx = {
    set(key: string, value: string) {
      sets.push({ key, value });
      return tx;
    },
    geoadd(key: string, lon: number, lat: number, member: string) {
      geoadds.push({ key, lon, lat, member });
      return tx;
    },
    publish(channel: string, payload: string) {
      published.push({ channel, payload });
      return tx;
    },
    async exec() {
      return [];
    },
  };
  const redis = {
    multi() {
      return tx;
    },
  };
  return { redis, published, geoadds, sets };
}

test("writeLive: publishes the delta to chan:<layer> and live:geo:<cell>", async () => {
  const { redis, published } = mockRedis();
  const env = {
    domain: "adsb",
    entity_id: "4ca7b3",
    ts: 1000,
    lon: 13.404954,
    lat: 52.520008,
    payload: { gs_kt: 440 },
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await writeLive(redis as any, env);
  const cell = encodeGeohash(env.lon, env.lat, 3);
  const channels = published.map((p) => p.channel).sort();
  assert.ok(channels.includes(channel("adsb")));
  assert.ok(channels.includes(geoChannel(cell)), `expected geo channel for cell ${cell}`);
  // The payload published is the full envelope JSON, identical on both channels.
  const payloads = new Set(published.map((p) => p.payload));
  assert.equal(payloads.size, 1);
  assert.deepEqual(JSON.parse([...payloads][0]!), env);
});

test("writeLive: a null-position envelope writes nothing (early return)", async () => {
  const { redis, published, sets } = mockRedis();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await writeLive(redis as any, { domain: "adsb", entity_id: "x", ts: 1, lon: null, lat: null });
  assert.equal(published.length, 0);
  assert.equal(sets.length, 0);
});

test("writeLive: sets the live key and geoadds the entity", async () => {
  const { redis, sets, geoadds } = mockRedis();
  const env = { domain: "ais", entity_id: "636092297", ts: 5, lon: 56.2, lat: 26.5 };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  await writeLive(redis as any, env);
  assert.equal(sets[0]?.key, "live:ais:636092297");
  assert.equal(geoadds[0]?.member, "636092297");
  assert.equal(geoadds[0]?.lon, 56.2);
});

// --- planSubscription (WS side viewport -> channels) ---

const ALL_LAYERS: Layer[] = ["adsb", "ais"];

test("planSubscription: no bbox -> global per-layer channels (back-compat)", () => {
  const plan = planSubscription(ALL_LAYERS, null, 3);
  assert.equal(plan.mode, "global");
  assert.deepEqual(plan.channels, [channel("adsb"), channel("ais")]);
});

test("planSubscription: precision 0 -> global channels even with a bbox", () => {
  const bbox: BBox = { w: 13, s: 52, e: 14, n: 53 };
  const plan = planSubscription(ALL_LAYERS, bbox, 0);
  assert.equal(plan.mode, "global");
  assert.deepEqual(plan.channels, [channel("adsb"), channel("ais")]);
});

test("planSubscription: a bbox -> geo cell channels covering the viewport, nothing else", () => {
  const bbox: BBox = { w: 13.0, s: 52.0, e: 13.001, n: 52.001 }; // tiny -> single cell
  const plan = planSubscription(ALL_LAYERS, bbox, 3);
  assert.equal(plan.mode, "geo");
  const cell = encodeGeohash(13.0005, 52.0005, 3);
  assert.deepEqual(plan.channels, [geoChannel(cell)]);
  // No global channels leak into a geo-mode subscription.
  assert.ok(!plan.channels.includes(channel("adsb")));
});

test("planSubscription: geo channels cover all four bbox corners", () => {
  const bbox: BBox = { w: 10, s: 40, e: 14, n: 44 };
  const precision = 3;
  const plan = planSubscription(ALL_LAYERS, bbox, precision);
  assert.equal(plan.mode, "geo");
  for (const [lon, lat] of [
    [bbox.w, bbox.s],
    [bbox.e, bbox.s],
    [bbox.w, bbox.n],
    [bbox.e, bbox.n],
  ] as const) {
    assert.ok(plan.channels.includes(geoChannel(encodeGeohash(lon, lat, precision))));
  }
});

test("planSubscription: an oversized viewport falls back to global channels", () => {
  const bbox: BBox = { w: -180, s: -90, e: 180, n: 90 };
  const plan = planSubscription(ALL_LAYERS, bbox, 5); // huge cover -> unbounded -> global
  assert.equal(plan.mode, "global");
  assert.deepEqual(plan.channels, [channel("adsb"), channel("ais")]);
});
