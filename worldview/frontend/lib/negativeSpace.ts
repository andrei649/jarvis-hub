// The negative-space grammar (spec §5.0, brief §7): disappearance rendered as evidence, not
// missing data. For each dark vessel we derive, when its feature carries a last known fix
// (`last_lon`/`last_lat`): a signal-loss GHOST at the exact last fix, a dashed DEAD-RECKONED
// path from there to the current estimate, and a faint uncertainty CONE widening along the
// heading. Without a last fix, the caption alone marks the loss. Zones the backend flags as
// `voided` get a dashed outline + caption. Pure, deterministic, unit-tested — ghosts and voids
// never animate (stillness IS the signal).

import type { Feature, FeatureCollection } from "./types";

export interface NsCaption {
  position: [number, number];
  text: string;
}

export interface NegativeSpace {
  /** Signal-loss markers (Point features rendered with the `ghost` icon). */
  ghosts: FeatureCollection;
  /** Dead-reckoned dashed paths (MultiLineString features, one dash per segment). */
  drPaths: FeatureCollection;
  /** Uncertainty cones (Polygon features). */
  cones: FeatureCollection;
  /** Dashed-outline polygons for zones flagged `voided` by the backend. */
  voidZones: FeatureCollection;
  captions: NsCaption[];
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

function empty(): NegativeSpace {
  return {
    ghosts: { ...EMPTY, features: [] },
    drPaths: { ...EMPTY, features: [] },
    cones: { ...EMPTY, features: [] },
    voidZones: { ...EMPTY, features: [] },
    captions: [],
  };
}

function pointOf(f: Feature): [number, number] | null {
  const g = f.geometry;
  if (g?.type === "Point" && Array.isArray(g.coordinates)) {
    const coords = g.coordinates as number[];
    const lon = coords[0];
    const lat = coords[1];
    if (typeof lon === "number" && typeof lat === "number" && Number.isFinite(lon) && Number.isFinite(lat)) {
      return [lon, lat];
    }
  }
  return null;
}

function clockUtc(ts: unknown): string | null {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return null;
  return new Date(n * 1000).toISOString().slice(11, 16);
}

/**
 * Split [from → to] into dash segments (a MultiLineString coordinate array) using a flat
 * lon/lat approximation — fine at choke-point scale. `dashFrac`/`gapFrac` are fractions of the
 * total length, so the dash pattern is resolution-independent and deterministic.
 */
export function dashSegments(
  from: [number, number],
  to: [number, number],
  dashFrac = 0.08,
  gapFrac = 0.06,
): [number, number][][] {
  const segs: [number, number][][] = [];
  const step = dashFrac + gapFrac;
  for (let t = 0; t < 1; t += step) {
    const end = Math.min(t + dashFrac, 1);
    segs.push([
      [from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t],
      [from[0] + (to[0] - from[0]) * end, from[1] + (to[1] - from[1]) * end],
    ]);
  }
  return segs;
}

/**
 * The uncertainty cone: a triangle from the last fix, opening ±`halfAngleDeg` around the
 * last-fix→estimate bearing, extended `lengthFactor`× past the estimate.
 */
export function uncertaintyCone(
  lastFix: [number, number],
  estimate: [number, number],
  halfAngleDeg = 12,
  lengthFactor = 1.3,
): [number, number][] {
  const dx = (estimate[0] - lastFix[0]) * lengthFactor;
  const dy = (estimate[1] - lastFix[1]) * lengthFactor;
  const a = (halfAngleDeg * Math.PI) / 180;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const left: [number, number] = [lastFix[0] + dx * cos - dy * sin, lastFix[1] + dx * sin + dy * cos];
  const right: [number, number] = [lastFix[0] + dx * cos + dy * sin, lastFix[1] - dx * sin + dy * cos];
  return [lastFix, left, right, lastFix];
}

/** Rough nm distance for the DR label (flat approximation; display-grade only). */
export function approxNm(a: [number, number], b: [number, number]): number {
  const latMid = ((a[1] + b[1]) / 2) * (Math.PI / 180);
  const dLonNm = (b[0] - a[0]) * 60 * Math.cos(latMid);
  const dLatNm = (b[1] - a[1]) * 60;
  return Math.sqrt(dLonNm * dLonNm + dLatNm * dLatNm);
}

export function buildNegativeSpace(context: FeatureCollection): NegativeSpace {
  const ns = empty();

  for (const f of context.features) {
    const props = f.properties ?? {};

    if (props.kind === "dark_vessel") {
      const estimate = pointOf(f);
      if (!estimate) continue;
      const lostAt = clockUtc(props.ts);

      const lastLon = Number(props.last_lon);
      const lastLat = Number(props.last_lat);
      const hasLastFix = Number.isFinite(lastLon) && Number.isFinite(lastLat);

      if (hasLastFix) {
        const lastFix: [number, number] = [lastLon, lastLat];
        ns.ghosts.features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: lastFix },
          properties: { ns: "ghost", mmsi: props.mmsi ?? null },
        });
        ns.drPaths.features.push({
          type: "Feature",
          geometry: { type: "MultiLineString", coordinates: dashSegments(lastFix, estimate) },
          properties: { ns: "dr-path", mmsi: props.mmsi ?? null },
        });
        ns.cones.features.push({
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [uncertaintyCone(lastFix, estimate)] },
          properties: { ns: "dr-cone", mmsi: props.mmsi ?? null },
        });
        ns.captions.push({
          position: lastFix,
          text: lostAt ? `signal lost ${lostAt}` : "signal lost",
        });
        ns.captions.push({
          position: estimate,
          text: `DR ±${Math.max(0.1, approxNm(lastFix, estimate) * 0.3).toFixed(1)}nm`,
        });
      } else if (lostAt) {
        // No last fix in the data — the loss is still announced at the estimated position.
        ns.captions.push({ position: estimate, text: `signal lost ${lostAt}` });
      }
      continue;
    }

    // Voided zones: rendered only when the backend flags them — we never invent absence.
    if (props.voided === true && f.geometry?.type === "Polygon") {
      ns.voidZones.features.push(f);
      const ring = (f.geometry.coordinates as [number, number][][])[0];
      if (ring && ring.length > 0) {
        const lon = ring.reduce((s, p) => s + p[0], 0) / ring.length;
        const lat = ring.reduce((s, p) => s + p[1], 0) / ring.length;
        ns.captions.push({
          position: [lon, lat],
          text: String(props.void_caption ?? "ZONE VOIDED"),
        });
      }
    }
  }

  return ns;
}
