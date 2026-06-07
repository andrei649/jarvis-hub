// Shared shapes for the 4D API.

export const LAYERS = ["adsb", "ais", "tle", "ew", "context"] as const;
export type Layer = (typeof LAYERS)[number];

export function isLayer(value: string): value is Layer {
  return (LAYERS as readonly string[]).includes(value);
}

export interface BBox {
  w: number;
  s: number;
  e: number;
  n: number;
}

/** Parse a "w,s,e,n" query string into a BBox, or null if absent/invalid. */
export function parseBBox(raw: string | undefined): BBox | null {
  if (!raw) return null;
  const parts = raw.split(",").map(Number);
  if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
  const [w, s, e, n] = parts as [number, number, number, number];
  return { w, s, e, n };
}

export interface GeoJSONFeature {
  type: "Feature";
  geometry: unknown;
  properties: Record<string, unknown>;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

// Liveness windows (seconds): how far back a track may be and still count as "present" at T.
export const LIVENESS_SECONDS: Record<Layer, number> = {
  adsb: 120,
  ais: 900,
  tle: 120,
  ew: 600,
  context: 0,
};

// Redis TTLs (seconds) for live-written entities, per the design doc §7.
export const LIVE_TTL_SECONDS: Record<string, number> = {
  adsb: 60,
  ais: 600,
  tle: 120,
  ew: 600,
};
