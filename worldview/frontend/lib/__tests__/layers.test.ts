import { test, expect } from "vitest";
import { LAYER_IDS } from "../layers";

test("the five canonical OSINT layers are registered", () => {
  expect(LAYER_IDS).toHaveLength(5);
  expect([...LAYER_IDS].sort()).toEqual(["adsb", "ais", "context", "ew", "tle"]);
});
