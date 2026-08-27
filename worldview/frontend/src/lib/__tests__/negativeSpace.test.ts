import { describe, expect, it } from "vitest";
import {
  approxNm,
  buildNegativeSpace,
  dashSegments,
  uncertaintyCone,
} from "../negativeSpace";
import type { FeatureCollection } from "../types";

function ctx(features: { geometry: unknown; properties: Record<string, unknown> }[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: features.map((f) => ({ type: "Feature", ...f })) as FeatureCollection["features"],
  };
}

const DARK_WITH_FIX = {
  geometry: { type: "Point", coordinates: [56.2, 26.3] },
  properties: {
    kind: "dark_vessel",
    mmsi: "244660000",
    ts: 1765538463, // 05:41 UTC
    gap_seconds: 3600,
    last_lon: 56.4,
    last_lat: 26.1,
  },
};

describe("buildNegativeSpace (spec §5.0 — absence rendered as evidence)", () => {
  it("dark vessel with a last fix → ghost + dashed DR path + cone + both captions", () => {
    const ns = buildNegativeSpace(ctx([DARK_WITH_FIX]));
    expect(ns.ghosts.features).toHaveLength(1);
    expect(ns.ghosts.features[0]?.geometry).toEqual({ type: "Point", coordinates: [56.4, 26.1] });
    expect(ns.drPaths.features).toHaveLength(1);
    const dashes = (ns.drPaths.features[0]?.geometry as { coordinates: unknown[] }).coordinates;
    expect(dashes.length).toBeGreaterThan(3); // a dashed path, not one solid segment
    expect(ns.cones.features).toHaveLength(1);
    const labels = ns.captions.map((c) => c.text);
    const lostClock = new Date(Number(DARK_WITH_FIX.properties.ts) * 1000)
      .toISOString()
      .slice(11, 16);
    expect(labels.some((l) => l === `signal lost ${lostClock}`)).toBe(true);
    expect(labels.some((l) => l.startsWith("DR ±"))).toBe(true);
  });

  it("dark vessel WITHOUT a last fix degrades to the caption alone (no invented geometry)", () => {
    const ns = buildNegativeSpace(
      ctx([
        {
          geometry: { type: "Point", coordinates: [56.2, 26.3] },
          properties: { kind: "dark_vessel", mmsi: "1", ts: 1765538463 },
        },
      ]),
    );
    expect(ns.ghosts.features).toHaveLength(0);
    expect(ns.drPaths.features).toHaveLength(0);
    expect(ns.cones.features).toHaveLength(0);
    expect(ns.captions).toHaveLength(1);
    expect(ns.captions[0]?.text).toContain("signal lost");
  });

  it("non-dark features produce nothing; voided zones only when the backend flags them", () => {
    const zone = {
      geometry: { type: "Polygon", coordinates: [[[55, 26], [57, 26], [57, 27], [55, 26]]] },
      properties: { kind: "event", category: "airspace_closure" },
    };
    expect(buildNegativeSpace(ctx([zone])).voidZones.features).toHaveLength(0);

    const voided = { ...zone, properties: { ...zone.properties, voided: true, void_caption: "AIRSPACE VOIDED — 14 TRACKS DEPARTED IN 22M" } };
    const ns = buildNegativeSpace(ctx([voided]));
    expect(ns.voidZones.features).toHaveLength(1);
    expect(ns.captions[0]?.text).toBe("AIRSPACE VOIDED — 14 TRACKS DEPARTED IN 22M");
  });
});

describe("geometry helpers", () => {
  it("dashSegments covers [from→to] with alternating gaps, deterministically", () => {
    const a = dashSegments([0, 0], [1, 0]);
    const b = dashSegments([0, 0], [1, 0]);
    expect(a).toEqual(b);
    expect(a.length).toBeGreaterThan(3);
    // First dash starts at `from`; every dash is a 2-point segment moving toward `to`.
    expect(a[0]?.[0]).toEqual([0, 0]);
    for (const seg of a) expect(seg[1]![0]).toBeGreaterThan(seg[0]![0]);
  });

  it("uncertaintyCone is a closed triangle anchored at the last fix", () => {
    const ring = uncertaintyCone([0, 0], [1, 0]);
    expect(ring).toHaveLength(4);
    expect(ring[0]).toEqual([0, 0]);
    expect(ring[3]).toEqual([0, 0]);
    // Opens symmetrically around the +x heading.
    expect(ring[1]![1]).toBeCloseTo(-ring[2]![1], 6);
  });

  it("approxNm: one degree of latitude ≈ 60 nm", () => {
    expect(approxNm([0, 0], [0, 1])).toBeCloseTo(60, 0);
  });
});
