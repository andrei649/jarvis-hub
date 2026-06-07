import { test, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchProvenance, formatTs, type Provenance } from "../provenance";

function okFetch(body: unknown) {
  return vi.fn(async () => ({
    ok: true,
    json: async () => body,
  }));
}

const ROW: Provenance = {
  layer: "ais",
  entityId: "636092297",
  source: "ais-stream-ingest",
  ts: 1749200000,
  ingestedAt: 1749200005,
};

beforeEach(() => vi.stubGlobal("fetch", okFetch({ provenance: null })));
afterEach(() => vi.unstubAllGlobals());

test("formatTs renders epoch-seconds as 'YYYY-MM-DD HH:MM:SS UTC'", () => {
  expect(formatTs(1749200000)).toBe("2025-06-06 08:53:20 UTC");
});

test("formatTs returns '—' for null/undefined/non-finite", () => {
  expect(formatTs(null)).toBe("—");
  expect(formatTs(undefined)).toBe("—");
  expect(formatTs(NaN)).toBe("—");
});

test("fetchProvenance builds /provenance/:layer/:id?t= with encoded id + floored t", async () => {
  vi.stubGlobal("fetch", okFetch({ provenance: ROW }));
  const out = await fetchProvenance("context", "evt/1 a", 1749200400.7);
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/provenance/context/evt%2F1%20a"); // entityId encoded
  expect(url).toContain("t=1749200400"); // floored, no fractional seconds
  expect(out).toEqual(ROW);
});

test("fetchProvenance omits t when not provided", async () => {
  vi.stubGlobal("fetch", okFetch({ provenance: ROW }));
  await fetchProvenance("ais", "636092297");
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/provenance/ais/636092297");
  expect(url).not.toContain("t=");
});

test("fetchProvenance returns null when the body carries provenance: null", async () => {
  vi.stubGlobal("fetch", okFetch({ provenance: null }));
  expect(await fetchProvenance("adsb", "4ca7b3", 1000)).toBeNull();
});

test("fetchProvenance returns null on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  expect(await fetchProvenance("adsb", "ffffff", 1000)).toBeNull();
});

test("fetchProvenance returns null when fetch throws", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("network down");
    }),
  );
  expect(await fetchProvenance("tle", "40115", 1000)).toBeNull();
});
