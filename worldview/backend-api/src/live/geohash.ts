// Geohash channel sharding (ticket H19.5.2). Pure, dependency-free geohash encoding plus a
// viewport→cell-set cover so the WS layer can subscribe a client only to the cells overlapping
// its bbox. We keep this self-contained (no external geohash dep) so the math is auditable and
// unit-tested against reference values.

import type { BBox } from "../types.js";

// Standard geohash base-32 alphabet (excludes a, i, l, o to avoid ambiguity).
const BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz";

/**
 * Encode a lon/lat to a geohash string of `precision` base-32 characters. This is the canonical
 * algorithm (interleaved lon/lat bits, MSB-first per character). Inputs are clamped to valid
 * WGS84 ranges so callers never produce out-of-range geohashes at the poles / antimeridian.
 */
export function encodeGeohash(lon: number, lat: number, precision: number): string {
  const p = Math.max(1, Math.floor(precision));
  let latMin = -90;
  let latMax = 90;
  let lonMin = -180;
  let lonMax = 180;
  // Clamp into range (defensive: a point exactly at 180/90 stays inside its edge cell).
  let clampedLon = Math.min(180, Math.max(-180, lon));
  let clampedLat = Math.min(90, Math.max(-90, lat));

  let hash = "";
  let bits = 0;
  let bitCount = 0;
  let evenBit = true; // even bits encode longitude, odd bits latitude

  while (hash.length < p) {
    if (evenBit) {
      const mid = (lonMin + lonMax) / 2;
      if (clampedLon >= mid) {
        bits = (bits << 1) | 1;
        lonMin = mid;
      } else {
        bits = bits << 1;
        lonMax = mid;
      }
    } else {
      const mid = (latMin + latMax) / 2;
      if (clampedLat >= mid) {
        bits = (bits << 1) | 1;
        latMin = mid;
      } else {
        bits = bits << 1;
        latMax = mid;
      }
    }
    evenBit = !evenBit;
    bitCount += 1;
    if (bitCount === 5) {
      hash += BASE32[bits];
      bits = 0;
      bitCount = 0;
    }
  }
  return hash;
}

/**
 * Approximate cell dimensions (degrees) for a geohash of the given precision. Each character adds
 * 5 bits, split as 3 lon / 2 lat on odd characters and 2 lon / 3 lat on even ones, so lon/lat bit
 * counts differ. Returns the cell width (lon span) and height (lat span) in degrees.
 */
export function cellSizeDegrees(precision: number): { lonStep: number; latStep: number } {
  const p = Math.max(1, Math.floor(precision));
  // Total bits = 5*p, split alternately starting with longitude.
  let lonBits = 0;
  let latBits = 0;
  for (let i = 0; i < 5 * p; i++) {
    if (i % 2 === 0) lonBits++;
    else latBits++;
  }
  return {
    lonStep: 360 / 2 ** lonBits,
    latStep: 180 / 2 ** latBits,
  };
}

// A hard cap on how many cells a single viewport may expand to. A world-spanning bbox at a fine
// precision could otherwise enumerate millions of cells; we bound the work and let the caller fall
// back to the global channel when the cover would be too large.
export const MAX_VIEWPORT_CELLS = 1024;

export interface ViewportCover {
  cells: string[];
  // True when the bbox was small enough to enumerate within MAX_VIEWPORT_CELLS. When false the
  // caller should fall back to the global channel (the cover would be unboundedly large).
  bounded: boolean;
}

/**
 * Compute the set of geohash cells (at `precision`) whose footprint overlaps the bbox. We walk the
 * grid of cell centers covering the bbox by stepping lonStep/latStep across it, guaranteeing every
 * corner and the interior is covered. The result is deduplicated and sorted for determinism.
 *
 * Bounded by MAX_VIEWPORT_CELLS: if the bbox is so large that the cover would exceed the cap, we
 * return `{ bounded:false }` and an empty list so the caller falls back to the global channel.
 */
export function viewportCells(bbox: BBox, precision: number): ViewportCover {
  const { lonStep, latStep } = cellSizeDegrees(precision);
  // Number of grid steps needed to span the bbox in each axis (+1 to include both edges, and an
  // extra to guarantee the far corner cell is hit even with float drift).
  const lonSteps = Math.floor((bbox.e - bbox.w) / lonStep) + 2;
  const latSteps = Math.floor((bbox.n - bbox.s) / latStep) + 2;
  if (lonSteps * latSteps > MAX_VIEWPORT_CELLS) {
    return { cells: [], bounded: false };
  }

  const set = new Set<string>();
  for (let li = 0; li < latSteps; li++) {
    // Sample slightly inside each cell (use the step grid anchored at the SW corner), clamped to
    // the bbox north edge so we always include the top row.
    const lat = Math.min(bbox.s + li * latStep, bbox.n);
    for (let lo = 0; lo < lonSteps; lo++) {
      const lon = Math.min(bbox.w + lo * lonStep, bbox.e);
      set.add(encodeGeohash(lon, lat, precision));
    }
    // Ensure the east edge column at this latitude is covered (float drift guard).
    set.add(encodeGeohash(bbox.e, lat, precision));
  }
  // Ensure all four corners are covered explicitly (belt-and-suspenders against rounding).
  set.add(encodeGeohash(bbox.w, bbox.s, precision));
  set.add(encodeGeohash(bbox.e, bbox.s, precision));
  set.add(encodeGeohash(bbox.w, bbox.n, precision));
  set.add(encodeGeohash(bbox.e, bbox.n, precision));

  return { cells: [...set].sort(), bounded: true };
}

// The per-cell pub/sub channel name. Deltas for entities inside a geohash cell are published here;
// a viewport-scoped client subscribes to exactly the cells covering its bbox.
export function geoChannel(cell: string): string {
  return `live:geo:${cell}`;
}
