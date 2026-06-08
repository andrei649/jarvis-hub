import { test, expect, vi, beforeEach, afterEach } from "vitest";
import {
  downloadBlob,
  encodeReplayWindow,
  decodeReplayWindow,
  buildReplayLink,
  extForFormat,
  mimeForFormat,
  featureCollectionToGeoJson,
  mergeFeatureCollections,
  fetchCaseExport,
  fetchReconstructionExport,
  type ReplayWindow,
} from "../export";
import type { FeatureCollection } from "../types";

function okFetch(body: string, contentType = "application/geo+json") {
  return vi.fn(async () => ({
    ok: true,
    text: async () => body,
    headers: { get: () => contentType },
  }));
}

beforeEach(() => vi.stubGlobal("fetch", okFetch("{}")));
afterEach(() => vi.unstubAllGlobals());

// --- download helper ---------------------------------------------------------

test("downloadBlob builds a Blob with the given content + MIME (node env: no document click)", () => {
  const blob = downloadBlob('{"a":1}', "x.json", "application/json");
  expect(blob).toBeInstanceOf(Blob);
  expect(blob.type).toBe("application/json");
  expect(blob.size).toBe('{"a":1}'.length);
});

test("downloadBlob passes a Blob through unchanged", () => {
  const src = new Blob(["hi"], { type: "text/plain" });
  const out = downloadBlob(src, "x.txt");
  expect(out).toBe(src);
});

test("mimeForFormat / extForFormat map formats correctly", () => {
  expect(mimeForFormat("geojson")).toBe("application/geo+json");
  expect(mimeForFormat("brief")).toBe("text/markdown");
  expect(mimeForFormat("json")).toBe("application/json");
  expect(extForFormat("geojson")).toBe("geojson");
  expect(extForFormat("brief")).toBe("md");
  expect(extForFormat("json")).toBe("json");
});

// --- in-memory serialization -------------------------------------------------

test("featureCollectionToGeoJson round-trips a FeatureCollection", () => {
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      { type: "Feature", geometry: { type: "Point", coordinates: [1, 2] }, properties: { a: 1 } },
    ],
  };
  expect(JSON.parse(featureCollectionToGeoJson(fc))).toEqual(fc);
});

test("mergeFeatureCollections tags each feature with its layer, preserving order", () => {
  const a: FeatureCollection = {
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: { id: "p1" } }],
  };
  const b: FeatureCollection = {
    type: "FeatureCollection",
    features: [{ type: "Feature", geometry: { type: "Point", coordinates: [1, 1] }, properties: { id: "p2" } }],
  };
  const merged = mergeFeatureCollections({ adsb: a, ais: b });
  expect(merged.features).toHaveLength(2);
  expect(merged.features[0]!.properties).toMatchObject({ layer: "adsb", id: "p1" });
  expect(merged.features[1]!.properties).toMatchObject({ layer: "ais", id: "p2" });
});

// --- backend export fetchers -------------------------------------------------

test("fetchCaseExport builds /cases/:id/export?format= and parses the body + content-type", async () => {
  vi.stubGlobal("fetch", okFetch("# Brief", "text/markdown"));
  const out = await fetchCaseExport("case 1", "brief");
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/cases/case%201/export");
  expect(url).toContain("format=brief");
  expect(out).toEqual({ body: "# Brief", contentType: "text/markdown" });
});

test("fetchCaseExport returns null on a non-ok response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  expect(await fetchCaseExport("c1", "geojson")).toBeNull();
});

test("fetchCaseExport returns null when fetch throws", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
  expect(await fetchCaseExport("c1")).toBeNull();
});

test("fetchReconstructionExport builds /reconstructions/:id/export?format= and parses", async () => {
  vi.stubGlobal("fetch", okFetch('{"type":"FeatureCollection"}', "application/geo+json"));
  const out = await fetchReconstructionExport("recon-9", "geojson");
  const url = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
  expect(url).toContain("/reconstructions/recon-9/export");
  expect(url).toContain("format=geojson");
  expect(out).toEqual({ body: '{"type":"FeatureCollection"}', contentType: "application/geo+json" });
});

test("fetchReconstructionExport falls back to the format MIME when no content-type header", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, text: async () => "{}", headers: { get: () => null } })));
  const out = await fetchReconstructionExport("r1", "json");
  expect(out).toEqual({ body: "{}", contentType: "application/json" });
});

test("fetchReconstructionExport returns null on a non-ok response and on throw", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false })));
  expect(await fetchReconstructionExport("r1")).toBeNull();
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("down"); }));
  expect(await fetchReconstructionExport("r1")).toBeNull();
});

// --- replay link encode/decode ----------------------------------------------

test("encodeReplayWindow floors times and joins bbox as w,s,e,n", () => {
  const q = encodeReplayWindow({ from: 1000.9, to: 2000.2, bbox: [55, 25, 58, 28] });
  expect(q).toContain("from=1000");
  expect(q).toContain("to=2000");
  expect(decodeURIComponent(q)).toContain("bbox=55,25,58,28");
});

test("encode → decode round-trips a window with bbox", () => {
  const win: ReplayWindow = { from: 1749200400, to: 1749286800, bbox: [55, 25, 58, 28] };
  expect(decodeReplayWindow(encodeReplayWindow(win))).toEqual(win);
});

test("encode → decode round-trips a window without bbox", () => {
  const win: ReplayWindow = { from: 100, to: 200 };
  const decoded = decodeReplayWindow(encodeReplayWindow(win));
  expect(decoded).toEqual({ from: 100, to: 200 });
  expect(decoded!.bbox).toBeUndefined();
});

test("decodeReplayWindow accepts a leading '?' and returns null without from/to", () => {
  expect(decodeReplayWindow("?from=1&to=2")).toEqual({ from: 1, to: 2 });
  expect(decodeReplayWindow("from=1")).toBeNull();
  expect(decodeReplayWindow("")).toBeNull();
});

test("decodeReplayWindow drops a malformed bbox but keeps the window", () => {
  const decoded = decodeReplayWindow("from=1&to=2&bbox=55,25,58");
  expect(decoded).toEqual({ from: 1, to: 2 });
});

test("buildReplayLink replaces query/hash and keeps origin + path", () => {
  const link = buildReplayLink("https://wv.app/globe?old=1#frag", { from: 10, to: 20 });
  expect(link.startsWith("https://wv.app/globe?")).toBe(true);
  expect(link).not.toContain("old=1");
  expect(link).not.toContain("#frag");
  expect(decodeReplayWindow(link.split("?")[1]!)).toEqual({ from: 10, to: 20 });
});
