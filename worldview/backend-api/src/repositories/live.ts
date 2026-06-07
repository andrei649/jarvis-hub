import type Redis from "ioredis";
import { emptyCollection } from "../geojson.js";
import { LIVE_TTL_SECONDS, type FeatureCollection, type GeoJSONFeature, type Layer } from "../types.js";

// Live state in Redis (design doc §7): one string key per entity (`live:<layer>:<id>`) holding
// its latest envelope, plus a geo set per layer. Keys carry a TTL = the liveness window, so a
// source that stops reporting an entity drops it off the globe automatically.

interface Envelope {
  domain: string;
  entity_id: string;
  ts: number;
  lon: number | null;
  lat: number | null;
  payload?: Record<string, unknown>;
}

export function liveKey(layer: string, entityId: string): string {
  return `live:${layer}:${entityId}`;
}

export function geoKey(layer: string): string {
  return `geo:${layer}`;
}

export function channel(layer: string): string {
  return `chan:${layer}`;
}

/** Upsert one envelope into the live cache and publish a delta (used by the live-writer). */
export async function writeLive(redis: Redis, env: Envelope): Promise<void> {
  if (env.lon == null || env.lat == null) return;
  const ttl = LIVE_TTL_SECONDS[env.domain] ?? 120;
  const key = liveKey(env.domain, env.entity_id);
  await redis
    .multi()
    .set(key, JSON.stringify(env), "EX", ttl)
    .geoadd(geoKey(env.domain), env.lon, env.lat, env.entity_id)
    .publish(channel(env.domain), JSON.stringify(env))
    .exec();
}

export function envelopeToFeature(env: Envelope): GeoJSONFeature {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [env.lon, env.lat] },
    properties: { entity_id: env.entity_id, ts: env.ts, ...(env.payload ?? {}) },
  };
}

/** Read the full live snapshot for a layer (every non-expired entity). */
export async function liveSnapshot(redis: Redis, layer: Layer): Promise<FeatureCollection> {
  const keys = await scanKeys(redis, `${liveKey(layer, "")}*`);
  if (keys.length === 0) return emptyCollection();
  const values = await redis.mget(keys);
  const features: GeoJSONFeature[] = [];
  for (const value of values) {
    if (value) features.push(envelopeToFeature(JSON.parse(value) as Envelope));
  }
  return { type: "FeatureCollection", features };
}

async function scanKeys(redis: Redis, pattern: string): Promise<string[]> {
  const found: string[] = [];
  let cursor = "0";
  do {
    const [next, batch] = await redis.scan(cursor, "MATCH", pattern, "COUNT", 500);
    found.push(...batch);
    cursor = next;
  } while (cursor !== "0");
  return found;
}
