import { test, expect, vi, afterEach } from "vitest";
import {
  shouldUseTiles,
  getTileConfig,
  buildTileLayerProps,
  isTileableLayer,
  DEFAULT_TILE_MAX_ZOOM,
  DEFAULT_TILE_MIN_ZOOM,
} from "../tiles";

const MVT = "https://tiles.example/{z}/{x}/{y}.pbf";

afterEach(() => vi.unstubAllEnvs());

// --- config / env parsing -------------------------------------------------

test("getTileConfig is disabled when NEXT_PUBLIC_TILE_URL is unset", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", "");
  const cfg = getTileConfig();
  expect(cfg.enabled).toBe(false);
  expect(cfg.url).toBe("");
});

test("getTileConfig reads url + zoom bounds from env", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "4");
  vi.stubEnv("NEXT_PUBLIC_TILE_MIN_ZOOM", "1");
  const cfg = getTileConfig();
  expect(cfg).toEqual({ url: MVT, maxZoom: 4, minZoom: 1, enabled: true });
});

test("getTileConfig falls back to defaults for missing/garbage zoom env", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "");
  vi.stubEnv("NEXT_PUBLIC_TILE_MIN_ZOOM", "not-a-number");
  const cfg = getTileConfig();
  expect(cfg.maxZoom).toBe(DEFAULT_TILE_MAX_ZOOM);
  expect(cfg.minZoom).toBe(DEFAULT_TILE_MIN_ZOOM);
});

test("getTileConfig trims whitespace-only url to disabled", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", "   ");
  expect(getTileConfig().enabled).toBe(false);
});

// --- shouldUseTiles -------------------------------------------------------

test("shouldUseTiles is false when no tile URL is configured (no-op default)", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", "");
  expect(shouldUseTiles(0)).toBe(false);
  expect(shouldUseTiles(2)).toBe(false);
});

test("shouldUseTiles is true at/below the threshold when configured", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "6");
  expect(shouldUseTiles(0)).toBe(true); // zoomed all the way out
  expect(shouldUseTiles(6)).toBe(true); // exactly at the threshold
});

test("shouldUseTiles is false above the threshold (zoomed in → points)", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "6");
  expect(shouldUseTiles(6.1)).toBe(false);
  expect(shouldUseTiles(12)).toBe(false);
});

test("shouldUseTiles honors an explicit maxZoom override", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  expect(shouldUseTiles(3, { maxZoom: 2 })).toBe(false);
  expect(shouldUseTiles(2, { maxZoom: 2 })).toBe(true);
});

test("shouldUseTiles never throws on a non-finite zoom", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  expect(shouldUseTiles(NaN)).toBe(false);
});

// --- buildTileLayerProps / tileable layers --------------------------------

test("buildTileLayerProps returns null when disabled", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", "");
  expect(buildTileLayerProps()).toBeNull();
});

test("buildTileLayerProps carries source url + zoom bounds when enabled", () => {
  vi.stubEnv("NEXT_PUBLIC_TILE_URL", MVT);
  vi.stubEnv("NEXT_PUBLIC_TILE_MAX_ZOOM", "5");
  vi.stubEnv("NEXT_PUBLIC_TILE_MIN_ZOOM", "0");
  expect(buildTileLayerProps()).toEqual({ data: MVT, minZoom: 0, maxZoom: 5 });
});

test("only the high-cardinality point layers are tileable", () => {
  expect(isTileableLayer("adsb")).toBe(true);
  expect(isTileableLayer("ais")).toBe(true);
  expect(isTileableLayer("tle")).toBe(false);
  expect(isTileableLayer("ew")).toBe(false);
  expect(isTileableLayer("context")).toBe(false);
});
