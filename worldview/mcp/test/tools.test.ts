// Unit tests for the pure WorldView MCP tool handlers (`src/tools.ts`).
//
// No network: every test injects a stub `fetchImpl` that records the URL it was called with and
// returns a canned GeoJSON FeatureCollection. We assert (a) the URL the handler builds and
// (b) the shape of the result it returns.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  RECONSTRUCT_EVENT_SCOPE,
  WATCH_AOI_SCOPE,
  findDarkVessels,
  listLayers,
  reconstructEvent,
  stateAt,
  trackOf,
  watchAoi,
  type Deps,
  type FeatureCollection,
  type FetchInit,
  type FetchLike,
} from "../src/tools.js";
import { signCapability, type CapabilityClaims } from "../src/auth.js";
import { WRITE_SCOPES, authorizeWrite } from "../src/server.js";

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

// --- WRITE tool handlers (watch_aoi / reconstruct_event) --------------------
//
// These are POSTs, so the stub records the `init` (method/body/headers) too. The handlers are
// pure: auth is enforced separately (see the auth-gate tests below), so here we only check the
// request the handler builds and its graceful non-2xx handling.

/** A stub `fetch` recording url + init and returning a canned JSON body with the given status. */
function stubWrite(
  body: unknown,
  status = 200,
): { fetchImpl: FetchLike; calls: { url: string; init?: FetchInit }[] } {
  const calls: { url: string; init?: FetchInit }[] = [];
  const fetchImpl: FetchLike = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    };
  };
  return { fetchImpl, calls };
}

test("watchAoi POSTs a watch rule and summarises the created watch", async () => {
  const { fetchImpl, calls } = stubWrite({ id: "watch-42" });
  const deps: Deps = { apiUrl: API, fetchImpl };

  const res = await watchAoi({ aoiId: "aoi-1", rule: "vessel-enters", lead: 300 }, deps);

  assert.equal(calls.length, 1);
  const u = new URL(calls[0]!.url);
  assert.equal(u.pathname, "/recon/watch");
  assert.equal(calls[0]!.init?.method, "POST");
  const sent = JSON.parse(calls[0]!.init!.body!);
  assert.deepEqual(sent, { aoiId: "aoi-1", rule: "vessel-enters", lead: 300 });
  assert.equal(res.isError, undefined);
  assert.match(res.content[0]!.text, /Watch created for AOI 'aoi-1'/);
  assert.match(res.content[0]!.text, /watch id watch-42/);
});

test("watchAoi rejects missing aoiId/rule without calling fetch", async () => {
  const { fetchImpl, calls } = stubWrite({});
  const deps: Deps = { apiUrl: API, fetchImpl };
  const res = await watchAoi({ aoiId: "", rule: "x" }, deps);
  assert.equal(res.isError, true);
  assert.equal(calls.length, 0);
});

test("watchAoi degrades to a clear error on a backend 5xx", async () => {
  const { fetchImpl } = stubWrite({ error: "boom" }, 500);
  const deps: Deps = { apiUrl: API, fetchImpl };
  const res = await watchAoi({ aoiId: "aoi-1", rule: "vessel-enters" }, deps);
  assert.equal(res.isError, true);
  assert.match(res.content[0]!.text, /HTTP 500/);
});

test("reconstructEvent POSTs the window and returns a job handle", async () => {
  const { fetchImpl, calls } = stubWrite({ jobId: "job-9", status: "accepted" });
  const deps: Deps = { apiUrl: API, fetchImpl };

  const res = await reconstructEvent(
    { from: 1699990000, to: 1700000000, layers: ["adsb", "ais"], bbox: "-5,50,5,55" },
    deps,
  );

  assert.equal(calls.length, 1);
  const u = new URL(calls[0]!.url);
  assert.equal(u.pathname, "/reconstruct");
  assert.equal(calls[0]!.init?.method, "POST");
  const sent = JSON.parse(calls[0]!.init!.body!);
  assert.deepEqual(sent, {
    from: 1699990000,
    to: 1700000000,
    bbox: "-5,50,5,55",
    layers: ["adsb", "ais"],
  });
  assert.equal(res.isError, undefined);
  assert.match(res.content[0]!.text, /Reconstruction 'job-9' requested/);
});

test("reconstructEvent rejects an invalid window / unknown layer without fetch", async () => {
  const { fetchImpl, calls } = stubWrite({});
  const deps: Deps = { apiUrl: API, fetchImpl };

  const bad = await reconstructEvent({ from: 100, to: 50 }, deps);
  assert.equal(bad.isError, true);
  assert.equal(calls.length, 0);

  const badLayer = await reconstructEvent({ from: 1, to: 2, layers: ["nope"] }, deps);
  assert.equal(badLayer.isError, true);
  assert.equal(calls.length, 0);
});

test("reconstructEvent degrades to a clear error on a backend 5xx", async () => {
  const { fetchImpl } = stubWrite({ error: "boom" }, 503);
  const deps: Deps = { apiUrl: API, fetchImpl };
  const res = await reconstructEvent({ from: 1, to: 2 }, deps);
  assert.equal(res.isError, true);
  assert.match(res.content[0]!.text, /HTTP 503/);
});

// --- Capability gate enforcement (authorizeWrite, from server.ts) -----------
//
// The server gates WRITE tools with `authorizeWrite` BEFORE the side effect. We inject the secret,
// a fixed clock, and an audit sink so the test is deterministic and self-contained: token fixtures
// are minted in-test with `signCapability`. Asserts the contract: a valid scoped token runs the
// handler (fetch called) and audits `allow`; a missing/invalid token rejects, NEVER calls fetch,
// and audits `deny`.

const GATE_SECRET = "test-secret";
const GATE_NOW = 1_700_000_000;

function gateToken(scopes: string[], ttl = 3600): string {
  const claims: CapabilityClaims = { scopes, exp: GATE_NOW + ttl, sub: "agent-x" };
  return signCapability(claims, GATE_SECRET);
}

test("scope constants line up with the server's WRITE_SCOPES map", () => {
  assert.equal(WRITE_SCOPES.watch_aoi, WATCH_AOI_SCOPE);
  assert.equal(WRITE_SCOPES.reconstruct_event, RECONSTRUCT_EVENT_SCOPE);
});

test("authorizeWrite runs watch_aoi with a valid scoped token and audits allow", async () => {
  const { fetchImpl, calls } = stubWrite({ id: "watch-1" });
  const deps: Deps = { apiUrl: API, fetchImpl };
  const audits: string[] = [];
  const token = gateToken([WATCH_AOI_SCOPE]);

  const res = await authorizeWrite(
    "watch_aoi",
    WATCH_AOI_SCOPE,
    { aoiId: "aoi-1", rule: "r", token },
    () => watchAoi({ aoiId: "aoi-1", rule: "r", token }, deps),
    { secret: GATE_SECRET, now: GATE_NOW, auditSink: (l) => audits.push(l) },
  );

  assert.equal(res.isError, undefined);
  assert.equal(calls.length, 1, "handler must have called fetch on an authorised request");
  assert.equal(audits.length, 1);
  const rec = JSON.parse(audits[0]!);
  assert.equal(rec.tool, "watch_aoi");
  assert.equal(rec.decision, "allow");
  assert.equal(rec.sub, "agent-x");
});

test("authorizeWrite rejects a missing token, never calls the handler, audits deny", async () => {
  const { fetchImpl, calls } = stubWrite({ id: "watch-1" });
  const deps: Deps = { apiUrl: API, fetchImpl };
  const audits: string[] = [];

  const res = await authorizeWrite(
    "watch_aoi",
    WATCH_AOI_SCOPE,
    { aoiId: "aoi-1", rule: "r" }, // no token
    () => watchAoi({ aoiId: "aoi-1", rule: "r" }, deps),
    { secret: GATE_SECRET, now: GATE_NOW, auditSink: (l) => audits.push(l) },
  );

  assert.equal(res.isError, true);
  assert.match(res.content[0]!.text, /UNAUTHORIZED/);
  assert.equal(calls.length, 0, "no side effect on an unauthorised request");
  assert.equal(audits.length, 1);
  const rec = JSON.parse(audits[0]!);
  assert.equal(rec.decision, "deny");
  assert.equal(rec.reason, "missing-token");
});

test("authorizeWrite rejects a token lacking the required scope (deny, no fetch)", async () => {
  const { fetchImpl, calls } = stubWrite({ jobId: "job-1" });
  const deps: Deps = { apiUrl: API, fetchImpl };
  const audits: string[] = [];
  // A watch-scoped token cannot drive a reconstruct.
  const token = gateToken([WATCH_AOI_SCOPE]);

  const res = await authorizeWrite(
    "reconstruct_event",
    RECONSTRUCT_EVENT_SCOPE,
    { from: 1, to: 2, token },
    () => reconstructEvent({ from: 1, to: 2, token }, deps),
    { secret: GATE_SECRET, now: GATE_NOW, auditSink: (l) => audits.push(l) },
  );

  assert.equal(res.isError, true);
  assert.equal(calls.length, 0);
  assert.equal(JSON.parse(audits[0]!).reason, "missing-scope");
});

test("authorizeWrite fails closed when no secret is configured (deny, no fetch)", async () => {
  const { fetchImpl, calls } = stubWrite({ id: "watch-1" });
  const deps: Deps = { apiUrl: API, fetchImpl };
  const audits: string[] = [];
  const token = gateToken([WATCH_AOI_SCOPE]);

  const res = await authorizeWrite(
    "watch_aoi",
    WATCH_AOI_SCOPE,
    { aoiId: "aoi-1", rule: "r", token },
    () => watchAoi({ aoiId: "aoi-1", rule: "r", token }, deps),
    { secret: undefined, now: GATE_NOW, auditSink: (l) => audits.push(l) },
  );

  assert.equal(res.isError, true);
  assert.equal(calls.length, 0);
  assert.equal(JSON.parse(audits[0]!).reason, "no-secret-configured");
});

test("authorizeWrite rejects a valid token whose authorised handler hits a 5xx", async () => {
  // Auth passes, so the handler runs and the backend 5xx surfaces as a graceful error result.
  const { fetchImpl, calls } = stubWrite({ error: "boom" }, 500);
  const deps: Deps = { apiUrl: API, fetchImpl };
  const audits: string[] = [];
  const token = gateToken([RECONSTRUCT_EVENT_SCOPE]);

  const res = await authorizeWrite(
    "reconstruct_event",
    RECONSTRUCT_EVENT_SCOPE,
    { from: 1, to: 2, token },
    () => reconstructEvent({ from: 1, to: 2, token }, deps),
    { secret: GATE_SECRET, now: GATE_NOW, auditSink: (l) => audits.push(l) },
  );

  assert.equal(JSON.parse(audits[0]!).decision, "allow");
  assert.equal(calls.length, 1);
  assert.equal(res.isError, true);
  assert.match(res.content[0]!.text, /HTTP 500/);
});
