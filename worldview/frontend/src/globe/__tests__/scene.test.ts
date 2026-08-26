import { test, expect, vi, afterEach } from "vitest";
import { buildScene } from "../scene";
import { LAYER_IDS, type LayerId } from "@/lib/layers";
import { emptyCollection, type Feature, type FeatureCollection } from "@/lib/types";
import type { LayerData } from "@/lib/layerData";

// The scene builder is deliberately Cesium-free, so the map's LAYER SELECTION and MARK ENCODINGS
// are testable in a node environment — no GPU, no canvas, no viewer.

const RASTER = "https://tiles.example/{z}/{x}/{y}.png";
const MVT = "https://tiles.example/{z}/{x}/{y}.pbf";

function emptyData(): LayerData {
  return LAYER_IDS.reduce((acc, id) => ({ ...acc, [id]: emptyCollection() }), {} as LayerData);
}

const allVisible = LAYER_IDS.reduce(
  (acc, id) => ({ ...acc, [id]: true }),
  {} as Record<LayerId, boolean>,
);

function point(coordinates: number[], properties: Record<string, unknown>): Feature {
  return { type: "Feature", geometry: { type: "Point", coordinates }, properties };
}

function collection(features: Feature[]): FeatureCollection {
  return { type: "FeatureCollection", features };
}

function layerIds(zoom?: number): string[] {
  return buildScene(emptyData(), allVisible, undefined, zoom).layerIds;
}

afterEach(() => vi.unstubAllEnvs());

// --- vector-tile switch (H19.5.1) -----------------------------------------

test("with no tile URL, adsb/ais stay as point layers at every zoom (no-op)", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const ids = layerIds(0);
  expect(ids).toContain("adsb");
  expect(ids).toContain("ais");
  expect(ids).not.toContain("adsb-tiles");
  expect(ids).not.toContain("ais-tiles");
});

test("zoomed out with a raster tile URL, the point layers are swapped for the overlay", () => {
  vi.stubEnv("VITE_TILE_URL", RASTER);
  vi.stubEnv("VITE_TILE_MAX_ZOOM", "6");
  const scene = buildScene(emptyData(), allVisible, undefined, 1); // below threshold
  expect(scene.layerIds).toContain("adsb-tiles");
  expect(scene.layerIds).toContain("ais-tiles");
  expect(scene.layerIds).not.toContain("adsb");
  expect(scene.layerIds).not.toContain("ais");
  expect(scene.tileOverlay).toEqual({ data: RASTER, minZoom: 0, maxZoom: 6 });
});

test("zoomed in with a tile URL, the point layers are kept (no tile swap)", () => {
  vi.stubEnv("VITE_TILE_URL", RASTER);
  vi.stubEnv("VITE_TILE_MAX_ZOOM", "6");
  const scene = buildScene(emptyData(), allVisible, undefined, 10); // above threshold
  expect(scene.layerIds).toContain("adsb");
  expect(scene.layerIds).toContain("ais");
  expect(scene.tileOverlay).toBeNull();
});

test("a vector tile URL never swaps the point layers — Cesium can't draw it", () => {
  vi.stubEnv("VITE_TILE_URL", MVT);
  const scene = buildScene(emptyData(), allVisible, undefined, 0);
  expect(scene.layerIds).toContain("adsb");
  expect(scene.tileOverlay).toBeNull();
});

test("the tile swap only affects adsb/ais — other layers are untouched", () => {
  vi.stubEnv("VITE_TILE_URL", RASTER);
  const ids = layerIds(0);
  expect(ids).toContain("tle");
  expect(ids).toContain("ew");
  expect(ids).toContain("context");
});

test("hidden layers contribute nothing", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const hidden = { ...allVisible, adsb: false, tle: false };
  const ids = buildScene(emptyData(), hidden, undefined, 8).layerIds;
  expect(ids).not.toContain("adsb");
  expect(ids).not.toContain("tle");
  expect(ids).toContain("ais");
});

// --- mark encodings (spec §1.2: shape + colour, never colour alone) --------

test("aircraft carry their altitude and heading; military flips the icon", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.adsb = collection([
    point([56.4, 26.6, 10668], { icao24: "abc123", track_deg: 275 }),
    point([56.5, 26.7, 3000], { icao24: "mil001", track_deg: 90, is_military: true }),
  ]);
  const marks = buildScene(data, allVisible, undefined, 8).points;
  expect(marks).toHaveLength(2);
  expect(marks[0]).toMatchObject({ icon: "civil", alt: 10668, rotationDeg: 275, trackId: "abc123" });
  expect(marks[1]).toMatchObject({ icon: "mil", alt: 3000, trackId: "mil001" });
});

test("vessels sit at sea level and are not directional", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.ais = collection([point([56.1, 26.1], { mmsi: "636092297", sog_kt: 11.2 })]);
  const mark = buildScene(data, allVisible, undefined, 8).points[0];
  expect(mark).toMatchObject({ icon: "vessel", alt: 0, rotationDeg: 0, trackId: "636092297" });
});

test("satellites keep their orbital altitude and draw their footprint polygon", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.tle = collection([
    point([56, 26, 617000], {
      norad_id: 40115,
      footprint: {
        type: "Polygon",
        coordinates: [[[55, 25], [57, 25], [57, 27], [55, 27], [55, 25]]],
      },
    }),
  ]);
  const scene = buildScene(data, allVisible, undefined, 4);
  expect(scene.points[0]).toMatchObject({ icon: "sat", alt: 617000, trackId: "40115" });
  expect(scene.polygons.some((p) => p.id.startsWith("tle-footprint"))).toBe(true);
});

test("a dark vessel renders the negative-space evidence, not just a mark", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.context = collection([
    point([56.9, 26.9], {
      kind: "dark_vessel",
      entity_id: "dv-1",
      mmsi: "636092297",
      ts: 1749200400,
      last_lon: 56.5,
      last_lat: 26.5,
    }),
  ]);
  const scene = buildScene(data, allVisible, undefined, 8);
  // the vessel itself, plus the ghost at its last known fix
  expect(scene.points.some((p) => p.icon === "dark")).toBe(true);
  expect(scene.points.some((p) => p.icon === "ghost")).toBe(true);
  // the dashed dead-reckoned path and the uncertainty cone
  expect(scene.polylines.some((l) => l.id.startsWith("ns-dr-path") && l.dashed)).toBe(true);
  expect(scene.polygons.some((p) => p.id.startsWith("ns-cone"))).toBe(true);
  // and the mono captions that name what happened
  expect(scene.labels.some((l) => l.text.startsWith("signal lost"))).toBe(true);
});

test("event points get a category callout; the selected trail becomes a polyline", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.context = collection([
    point([56.2, 26.2], { kind: "event", entity_id: "ev-1", category: "airspace closure" }),
  ]);
  const track: FeatureCollection = collection([
    {
      type: "Feature",
      geometry: { type: "LineString", coordinates: [[56, 26], [56.2, 26.2], [56.4, 26.4]] },
      properties: {},
    },
  ]);
  const scene = buildScene(data, allVisible, track, 8);
  expect(scene.labels.some((l) => l.text === "airspace closure")).toBe(true);
  expect(scene.layerIds).toContain("track");
  expect(scene.polylines.find((l) => l.id.startsWith("track"))?.positions).toHaveLength(3);
});

test("a feature with unusable geometry is skipped, not rendered at null island", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.ais = collection([
    point([Number.NaN, 26.1], { mmsi: "broken" }),
    point([56.1, 26.1], { mmsi: "good" }),
  ]);
  const marks = buildScene(data, allVisible, undefined, 8).points;
  expect(marks).toHaveLength(1);
  expect(marks[0]!.trackId).toBe("good");
});

test("every mark id is unique, so frame diffing can key on it", () => {
  vi.stubEnv("VITE_TILE_URL", "");
  const data = emptyData();
  data.adsb = collection([
    point([56.4, 26.6, 1000], { icao24: "abc123" }),
    point([56.5, 26.7, 1000], { icao24: "def456" }),
  ]);
  data.ais = collection([point([56.1, 26.1], { mmsi: "abc123" })]); // same id, different layer
  const ids = buildScene(data, allVisible, undefined, 8).points.map((p) => p.id);
  expect(new Set(ids).size).toBe(ids.length);
});
