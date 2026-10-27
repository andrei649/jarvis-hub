import { test, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

// The keyless basemap depends on files INSIDE the cesium package, not on any API we call. If a
// Cesium upgrade ever moved or dropped Assets/Textures/NaturalEarthII, the globe would silently
// fall back to a blank blue ball at runtime — so assert the contract here, at build time.

const require = createRequire(import.meta.url);
const packageJson = require.resolve("cesium/package.json");
const cesiumRoot = join(dirname(packageJson), "Build", "Cesium");

test("cesium is pinned to an exact version", () => {
  const pinnedVersion = "1.146.0";
  const manifest = JSON.parse(readFileSync(new URL("../../../package.json", import.meta.url), "utf8"));
  const lock = JSON.parse(readFileSync(new URL("../../../../package-lock.json", import.meta.url), "utf8"));
  const version = JSON.parse(readFileSync(packageJson, "utf8")).version as string;
  expect(manifest.dependencies.cesium).toBe(pinnedVersion);
  expect(lock.packages["node_modules/cesium"].version).toBe(pinnedVersion);
  expect(version).toBe(pinnedVersion);
});

test("the bundled Natural Earth II basemap ships inside the package", () => {
  const tiles = join(cesiumRoot, "Assets", "Textures", "NaturalEarthII");
  expect(existsSync(tiles)).toBe(true);
  // TileMapServiceImageryProvider.fromUrl() reads this descriptor to learn the tiling scheme.
  expect(existsSync(join(tiles, "tilemapresource.xml"))).toBe(true);
});

test("the runtime asset directories the app mirrors into public/ all exist", () => {
  for (const dir of ["Assets", "Workers", "ThirdParty", "Widgets"]) {
    expect(existsSync(join(cesiumRoot, dir))).toBe(true);
  }
});

test("the widget stylesheet the viewer imports is present", () => {
  expect(existsSync(join(cesiumRoot, "Widgets", "widgets.css"))).toBe(true);
});
