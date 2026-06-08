import { test, expect, vi, afterEach } from "vitest";

// Deck.gl's real layer classes pull luma.gl/WebGL, which doesn't resolve under vitest's node
// env. We don't need real GL here — only that buildLayers picks the tile class for adsb/ais
// when zoomed out. Mock each layer class to a plain object that echoes back its `id`, so the
// returned layer list is inspectable by id.
vi.mock("@deck.gl/layers", () => ({
  GeoJsonLayer: class {
    id: string;
    constructor(props: { id: string }) {
      this.id = props.id;
    }
  },
  TextLayer: class {
    id: string;
    constructor(props: { id: string }) {
      this.id = props.id;
    }
  },
}));
vi.mock("../mvtLayer", () => ({
  MVTLayer: class {
    id: string;
    constructor(props: { id: string }) {
      this.id = props.id;
    }
  },
}));

import { buildLayers } from "../deckLayers";
import { LAYER_IDS, type LayerId } from "../layers";
import { emptyCollection, type FeatureCollection } from "../types";

const MVT = "https://tiles.example/{z}/{x}/{y}.pbf";

function emptyData(): Record<LayerId, FeatureCollection> {
  return LAYER_IDS.reduce(
    (acc, id) => ({ ...acc, [id]: emptyCollection() }),
    {} as Record<LayerId, FeatureCollection>,
  );
}
const allVisible = LAYER_IDS.reduce(
  (acc, id) => ({ ...acc, [id]: true }),
  {} as Record<LayerId, boolean>,
);

function layerIds(zoom?: number): string[] {
  return buildLayers(emptyData(), allVisible, undefined, zoom).map((l) => l.id);
}

afterEach(() => vi.unstubAllEnvs());

test("with no tile URL, adsb/ais stay as point layers at every zoom (no-op)", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", "");
  const ids = layerIds(0);
  expect(ids).toContain("adsb");
  expect(ids).toContain("ais");
  expect(ids).not.toContain("adsb-tiles");
  expect(ids).not.toContain("ais-tiles");
});

test("zoomed out with a tile URL, the scatter layers are swapped for tile layers", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "6");
  const ids = layerIds(1); // below threshold
  expect(ids).toContain("adsb-tiles");
  expect(ids).toContain("ais-tiles");
  expect(ids).not.toContain("adsb");
  expect(ids).not.toContain("ais");
});

test("zoomed in with a tile URL, the point layers are kept (no tile swap)", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "6");
  const ids = layerIds(10); // above threshold
  expect(ids).toContain("adsb");
  expect(ids).toContain("ais");
  expect(ids).not.toContain("adsb-tiles");
  expect(ids).not.toContain("ais-tiles");
});

test("tile swap only affects adsb/ais — other layers are untouched", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  const ids = layerIds(0);
  expect(ids).toContain("tle");
  expect(ids).toContain("ew");
  expect(ids).toContain("context");
});
