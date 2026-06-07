// Unit tests for the pure WorldView MCP tool handlers (`src/tools.ts`).
//
// No network: every test injects a stub `fetchImpl` that records the URL it was called with and
// returns a canned GeoJSON FeatureCollection. We assert (a) the URL the handler builds and
// (b) the shape of the result it returns.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  findDarkVessels,
  listLayers,
  stateAt,
  trackOf,
  type Deps,
  type FeatureCollection,
  type FetchLike,
} from "../src/tools.js";

const API = "http://localhost:4000";

/** A stub `fetch` that captures the requested URL and returns the given FeatureCollection. */
function stubFetch(fc: FeatureCollection): { fetchImpl: FetchLike; urls: string[] } {
  const urls: string[] = [];
  const fetchImpl: FetchLike = async (url: string) => {
    urls.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => fc,
      text: async () => JSON.stringify(fc),
    };
  };
  return { fetchImpl, urls };
}

function depsWith(fc: FeatureCollection): { deps: Deps; urls: string[] } {
  const { fetchImpl, urls } = stubFetch(fc);
  return { deps: { apiUrl: API, fetchImpl }, urls };
}

const emptyFC: FeatureCollection = { type: "FeatureCollection", features: [] };

function feature(props: Record<string, unknown>) {
  return { type: "Feature" as const, geometry: { type: "Point", coordinates: [0, 0] }, properties: props };
}

// --- state_at ---------------------------------------------------------------

test("stateAt builds the right URL and returns the FeatureCollection", async () => {
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: [feature({ icao: "abc123" }), feature({ icao: "def456" })],
  };
  const { deps, urls } = depsWith(fc);

  const res = await stateAt({ layer: "adsb", t: 1700000000, bbox: "-10,40,10,60" }, deps);

  assert.equal(urls.length, 1);
  const u = new URL(urls[0]!);
  assert.equal(u.pathname, "/history/adsb");
  assert.equal(u.searchParams.get("t"), "1700000000");
  assert.equal(u.searchParams.get("bbox"), "-10,40,10,60");
  assert.equal(res.isError, undefined);
  // The result text carries a summary line plus the stringified FeatureCollection.
  assert.match(res.content[0]!.text, /2 features in layer 'adsb'/);
  const parsed = JSON.parse(res.content[0]!.text.split("\n").slice(1).join("\n"));
  assert.equal(parsed.type, "FeatureCollection");
  assert.equal(parsed.features.length, 2);
});

test("stateAt forwards the lod query param", async () => {
  const { deps, urls } = depsWith(emptyFC);
  await stateAt({ layer: "ais", t: 1700000000, lod: "minute" }, deps);
  const u = new URL(urls[0]!);
  assert.equal(u.searchParams.get("lod"), "minute");
});

test("stateAt rejects an invalid layer without calling fetch", async () => {
  const { deps, urls } = depsWith(emptyFC);
  const res = await stateAt({ layer: "nope", t: 1700000000 }, deps);
  assert.equal(res.isError, true);
  assert.equal(urls.length, 0);
  assert.match(res.content[0]!.text, /Invalid layer/);
});

test("stateAt rejects a non-numeric t", async () => {
  const { deps, urls } = depsWith(emptyFC);
  const res = await stateAt({ layer: "adsb", t: "not-a-number" }, deps);
  assert.equal(res.isError, true);
  assert.equal(urls.length, 0);
});

// --- find_dark_vessels ------------------------------------------------------

test("findDarkVessels queries the context layer and filters to dark vessels", async () => {
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: [
      feature({ kind: "dark_vessel", mmsi: "111" }),
      feature({ kind: "notam" }),
      feature({ kind: "event" }),
      feature({ kind: "dark_vessel", mmsi: "222" }),
    ],
  };
  const { deps, urls } = depsWith(fc);

  const res = await findDarkVessels({ t: 1700000000, bbox: "-5,50,5,55" }, deps);

  const u = new URL(urls[0]!);
  assert.equal(u.pathname, "/history/context");
  assert.equal(u.searchParams.get("t"), "1700000000");
  assert.equal(u.searchParams.get("bbox"), "-5,50,5,55");
  assert.equal(res.isError, undefined);
  assert.match(res.content[0]!.text, /2 dark vessels/);
  const parsed = JSON.parse(res.content[0]!.text.split("\n").slice(1).join("\n"));
  assert.equal(parsed.features.length, 2);
  for (const f of parsed.features) assert.equal(f.properties.kind, "dark_vessel");
});

test("findDarkVessels rejects a non-numeric t", async () => {
  const { deps, urls } = depsWith(emptyFC);
  const res = await findDarkVessels({ t: "x" }, deps);
  assert.equal(res.isError, true);
  assert.equal(urls.length, 0);
});

// --- track_of ---------------------------------------------------------------

test("trackOf builds the /track URL with from/to", async () => {
  const fc: FeatureCollection = {
    type: "FeatureCollection",
    features: [feature({ entityId: "abc123" })],
  };
  const { deps, urls } = depsWith(fc);

  const res = await trackOf({ layer: "adsb", entityId: "abc123", from: 1699990000, to: 1700000000 }, deps);

  const u = new URL(urls[0]!);
  assert.equal(u.pathname, "/history/adsb/abc123/track");
  assert.equal(u.searchParams.get("from"), "1699990000");
  assert.equal(u.searchParams.get("to"), "1700000000");
  assert.equal(res.isError, undefined);
  assert.match(res.content[0]!.text, /Track for 'abc123' in layer 'adsb'/);
});

test("trackOf omits from/to when not provided and url-encodes the entityId", async () => {
  const { deps, urls } = depsWith(emptyFC);
  await trackOf({ layer: "ais", entityId: "MM SI/1" }, deps);
  const u = new URL(urls[0]!);
  assert.equal(u.pathname, "/history/ais/MM%20SI%2F1/track");
  assert.equal(u.searchParams.get("from"), null);
  assert.equal(u.searchParams.get("to"), null);
});

test("trackOf rejects a non-trackable layer without calling fetch", async () => {
  const { deps, urls } = depsWith(emptyFC);
  const res = await trackOf({ layer: "context", entityId: "x" }, deps);
  assert.equal(res.isError, true);
  assert.equal(urls.length, 0);
  assert.match(res.content[0]!.text, /Invalid track layer/);
});

test("trackOf rejects a missing entityId", async () => {
  const { deps, urls } = depsWith(emptyFC);
  const res = await trackOf({ layer: "adsb", entityId: "" }, deps);
  assert.equal(res.isError, true);
  assert.equal(urls.length, 0);
});

// --- HTTP error handling ----------------------------------------------------

test("stateAt surfaces a non-2xx HTTP response as an error result", async () => {
  const fetchImpl: FetchLike = async () => ({
    ok: false,
    status: 404,
    json: async () => ({}),
    text: async () => "unknown layer",
  });
  const res = await stateAt({ layer: "adsb", t: 1700000000 }, { apiUrl: API, fetchImpl });
  assert.equal(res.isError, true);
  assert.match(res.content[0]!.text, /HTTP 404/);
});

// --- list_layers ------------------------------------------------------------

test("listLayers returns all five layers with descriptions, no network", () => {
  const res = listLayers();
  assert.equal(res.isError, undefined);
  for (const layer of ["adsb", "ais", "tle", "ew", "context"]) {
    assert.ok(res.content[0]!.text.includes(layer), `expected layer ${layer} in output`);
  }
  const payload = JSON.parse(res.content[0]!.text.split("\n").pop()!);
  assert.equal(payload.layers.length, 5);
});
