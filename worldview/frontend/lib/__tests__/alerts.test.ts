import { test, expect } from "vitest";
import { deriveAlerts } from "../alerts";
import { emptyCollection } from "../types";
import type { LayerData } from "../useWorldViewData";
import type { FeatureCollection } from "../types";

// Build a LayerData with only the context layer populated (the others are empty collections).
function layerData(context: FeatureCollection): LayerData {
  return {
    adsb: emptyCollection(),
    ais: emptyCollection(),
    tle: emptyCollection(),
    ew: emptyCollection(),
    context,
  };
}

const NOW = 1_700_000_000;

test("derives sorted alerts from a dark vessel + an event", () => {
  const context: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [12.5, 41.9] },
        properties: {
          kind: "event",
          category: "missile_launch",
          severity: 0.5,
          ts: NOW - 100,
          entity_id: "evt-1",
        },
      },
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [30.1, 45.3] },
        properties: {
          kind: "dark_vessel",
          mmsi: 273123456,
          gap_seconds: 3600,
          ts: NOW - 50,
          entity_id: "273123456",
        },
      },
    ],
  };

  const alerts = deriveAlerts(layerData(context), NOW);

  expect(alerts).toHaveLength(2);

  // Dark vessel (high) sorts before the medium-severity event.
  const first = alerts[0]!;
  const second = alerts[1]!;
  expect(first.kind).toBe("dark_vessel");
  expect(first.severity).toBe("high");
  expect(first.label).toBe("Dark vessel MMSI 273123456 (gap 3600s)");
  expect(first.entityId).toBe("273123456");
  expect(first.lon).toBe(30.1);
  expect(first.lat).toBe(45.3);

  expect(second.kind).toBe("event");
  expect(second.severity).toBe("medium");
  expect(second.label).toBe("missile_launch (sev 0.5)");
});

test("empty context yields no alerts", () => {
  expect(deriveAlerts(layerData(emptyCollection()), NOW)).toEqual([]);
});

test("ignores non-Point geometries for position but still alerts", () => {
  const context: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
        properties: { kind: "event", category: "zone_breach", severity: 0.9, ts: NOW },
      },
    ],
  };

  const alert = deriveAlerts(layerData(context), NOW)[0]!;
  expect(alert.kind).toBe("event");
  expect(alert.severity).toBe("high");
  expect(alert.lon).toBeUndefined();
  expect(alert.lat).toBeUndefined();
});
