import { test, expect, vi, afterEach } from "vitest";
import { basemapChoice, ionToken } from "../basemap";

// The token-less floor is a product promise, not an implementation detail: with no credentials
// the globe still draws a real Earth from tiles bundled inside the Cesium package.

afterEach(() => vi.unstubAllEnvs());

test("with no ion token the basemap is the bundled Natural Earth II, and says so", () => {
  vi.stubEnv("VITE_CESIUM_ION_TOKEN", "");
  const choice = basemapChoice();
  expect(choice.kind).toBe("natural-earth");
  expect(choice.terrain).toBe(false);
  expect(choice.detail).toContain("no token");
});

test("with an ion token the basemap upgrades to world imagery + terrain", () => {
  vi.stubEnv("VITE_CESIUM_ION_TOKEN", "eyJhbGciOi.test.token");
  const choice = basemapChoice();
  expect(choice.kind).toBe("ion");
  expect(choice.terrain).toBe(true);
});

test("a whitespace-only token is not a token", () => {
  vi.stubEnv("VITE_CESIUM_ION_TOKEN", "   ");
  expect(ionToken()).toBe("");
  expect(basemapChoice().kind).toBe("natural-earth");
});
