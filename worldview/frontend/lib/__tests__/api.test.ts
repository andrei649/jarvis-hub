import { test, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchHistory, fetchTrack } from "../api";

function okFetch() {
  return vi.fn(async () => ({
    ok: true,
    json: async () => ({ type: "FeatureCollection", features: [] }),
  }));
}

beforeEach(() => vi.stubGlobal("fetch", okFetch()));
afterEach(() => vi.unstubAllGlobals());

test("fetchHistory builds /history/:layer with floored t and a bbox", async () => {
  await fetchHistory("adsb", 1749200400.7, [55, 25, 58, 28]);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/adsb");
  expect(url).toContain("t=1749200400"); // floored, no fractional seconds
  expect(url).toContain("bbox=55%2C25%2C58%2C28"); // comma-encoded w,s,e,n
});

test("fetchHistory omits bbox when not provided", async () => {
  await fetchHistory("ais", 1000);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/ais");
  expect(url).not.toContain("bbox=");
});

test("fetchHistory returns an empty FeatureCollection on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  const fc = await fetchHistory("ew", 1);
  expect(fc).toEqual({ type: "FeatureCollection", features: [] });
});

test("fetchHistory returns an empty FeatureCollection when fetch throws", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {
    throw new Error("network down");
  }));
  const fc = await fetchHistory("tle", 1);
  expect(fc.features).toEqual([]);
});

test("fetchTrack builds the /track URL with floored from/to and encoded id", async () => {
  await fetchTrack("ais", "636092297", 1000.9, 4600.2);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/history/ais/636092297/track");
  expect(url).toContain("from=1000");
  expect(url).toContain("to=4600");
});
