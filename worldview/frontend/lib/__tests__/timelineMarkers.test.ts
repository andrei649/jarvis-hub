import { describe, expect, it } from "vitest";
import { deriveTimelineMarkers, markerPct } from "../timelineMarkers";
import { emptyCollection, type FeatureCollection } from "../types";
import type { LayerData } from "../useWorldViewData";
import type { ReconWindow } from "../recon";

function context(features: Record<string, unknown>[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: features.map((properties) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [56, 26] },
      properties,
    })),
  };
}

function layerData(ctx: FeatureCollection): LayerData {
  return { adsb: emptyCollection(), ais: emptyCollection(), tle: emptyCollection(), ew: emptyCollection(), context: ctx };
}

const recon: ReconWindow[] = [
  {
    norad_id: 43437,
    aoi_id: "hormuz",
    sensor_type: "sar",
    t_ingress: 2000,
    t_peak: 2100,
    t_egress: 2200,
    min_distance_km: 12,
    sunlit_at_peak: false,
    quality: 0.87,
  },
];

describe("deriveTimelineMarkers", () => {
  it("dark vessels are red alert ticks; recon ingresses are gold; both sorted by time", () => {
    const data = layerData(
      context([{ kind: "dark_vessel", mmsi: "1", entity_id: "d1", ts: 3000, gap_seconds: 60 }]),
    );
    const markers = deriveTimelineMarkers(data, recon, 5000);
    expect(markers.map((m) => m.kind)).toEqual(["recon", "alert"]);
    expect(markers[0]?.label).toContain("SAR pass");
    expect(markers[1]?.t).toBe(3000);
  });

  it("low-severity events are violet intel, high-severity events are alerts", () => {
    const data = layerData(
      context([
        { kind: "event", category: "strike", severity: 0.9, entity_id: "e1", ts: 100 },
        { kind: "event", category: "drill", severity: 0.1, entity_id: "e2", ts: 200 },
      ]),
    );
    const kinds = Object.fromEntries(deriveTimelineMarkers(data, [], 0).map((m) => [m.t, m.kind]));
    expect(kinds[100]).toBe("alert");
    expect(kinds[200]).toBe("intel");
  });

  it("drops markers without a usable timestamp", () => {
    const data = layerData(context([{ kind: "dark_vessel", mmsi: "1", entity_id: "d1" }]));
    expect(deriveTimelineMarkers(data, [], 0)).toEqual([]);
  });
});

describe("markerPct", () => {
  it("maps a timestamp into the window as 0–100", () => {
    expect(markerPct(50, 0, 100)).toBe(50);
    expect(markerPct(0, 0, 100)).toBe(0);
    expect(markerPct(100, 0, 100)).toBe(100);
  });

  it("returns null outside the window or for a degenerate window", () => {
    expect(markerPct(-1, 0, 100)).toBeNull();
    expect(markerPct(101, 0, 100)).toBeNull();
    expect(markerPct(5, 10, 10)).toBeNull();
  });
});
