// Pure, testable tool handlers for the WorldView MCP server.
//
// Each handler takes `(args, deps)` where `deps` injects the backend base URL and a `fetch`
// implementation so tests can stub the network. Handlers never throw on a *handled* error
// (bad input, non-2xx response): they return a `ToolResult` with `isError: true` and a clear
// message, which the MCP server turns into an error tool result for the client.

/** The five WorldView 4D layers, as enforced by the backend (`backend-api/src/types.ts`). */
export const LAYERS = ["adsb", "ais", "tle", "ew", "context"] as const;
export type Layer = (typeof LAYERS)[number];

/** Layers that expose a per-entity `/track` endpoint (adsb/ais/tle). */
export const TRACK_LAYERS = ["adsb", "ais", "tle"] as const;
export type TrackLayer = (typeof TRACK_LAYERS)[number];

export type Lod = "raw" | "minute";

/** One-line descriptions for each layer, surfaced by the `list_layers` tool. */
export const LAYER_DESCRIPTIONS: Record<Layer, string> = {
  adsb: "Aircraft positions from ADS-B transponders.",
  ais: "Vessel positions from AIS maritime transponders.",
  tle: "Satellite positions propagated from TLE orbital elements.",
  ew: "Electronic-warfare / RF emitter detections.",
  context: "Derived context overlays (NOTAMs, strike zones, events, dark vessels).",
};

// Minimal GeoJSON shapes — we only need enough structure to filter and summarise.
export interface GeoJSONFeature {
  type: "Feature";
  geometry: unknown;
  properties: Record<string, unknown>;
}
export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

/** The `init` fields we use — supports both reads (GET) and writes (POST with a JSON body). */
export interface FetchInit {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

/** Subset of the WHATWG `fetch` we depend on — keeps stubbing trivial in tests. */
export type FetchLike = (
  url: string,
  init?: FetchInit,
) => Promise<{
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text?: () => Promise<string>;
}>;

export interface Deps {
  apiUrl: string;
  fetchImpl: FetchLike;
}

/** Standard MCP-style tool result: text content blocks, optionally flagged as an error. */
export interface ToolResult {
  content: { type: "text"; text: string }[];
  isError?: boolean;
}

function ok(text: string): ToolResult {
  return { content: [{ type: "text", text }] };
}
function err(text: string): ToolResult {
  return { content: [{ type: "text", text }], isError: true };
}

function isLayer(value: unknown): value is Layer {
  return typeof value === "string" && (LAYERS as readonly string[]).includes(value);
}
function isTrackLayer(value: unknown): value is TrackLayer {
  return typeof value === "string" && (TRACK_LAYERS as readonly string[]).includes(value);
}

/** Coerce a numeric arg that may arrive as a number or numeric string; null if invalid. */
function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

/** Build an absolute URL onto the backend, appending only defined query params. */
function buildUrl(apiUrl: string, path: string, params: Record<string, string | undefined>): string {
  const url = new URL(path.replace(/^\//, ""), apiUrl.endsWith("/") ? apiUrl : apiUrl + "/");
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) url.searchParams.set(key, value);
  }
  return url.toString();
}

/** Fetch a GeoJSON FeatureCollection, mapping network/HTTP failures into a ToolResult error. */
async function fetchCollection(
  url: string,
  deps: Deps,
): Promise<{ ok: true; fc: FeatureCollection } | { ok: false; result: ToolResult }> {
  let res: Awaited<ReturnType<FetchLike>>;
  try {
    res = await deps.fetchImpl(url);
  } catch (e) {
    return { ok: false, result: err(`Request to WorldView API failed: ${(e as Error).message} (${url})`) };
  }
  if (!res.ok) {
    let detail = "";
    if (typeof res.text === "function") {
      try {
        detail = await res.text();
      } catch {
        /* ignore body read errors */
      }
    }
    return {
      ok: false,
      result: err(`WorldView API returned HTTP ${res.status} for ${url}${detail ? `: ${detail}` : ""}`),
    };
  }
  const body = (await res.json()) as FeatureCollection;
  return { ok: true, fc: body };
}

/**
 * POST a JSON body and parse a JSON response, mapping network/HTTP failures into a ToolResult
 * error (the WRITE-tool analogue of `fetchCollection`). The backend route may not exist yet; a
 * non-2xx therefore degrades to a clear error result rather than throwing.
 */
async function postJson(
  url: string,
  payload: unknown,
  deps: Deps,
): Promise<{ ok: true; body: unknown } | { ok: false; result: ToolResult }> {
  let res: Awaited<ReturnType<FetchLike>>;
  try {
    res = await deps.fetchImpl(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return { ok: false, result: err(`Request to WorldView API failed: ${(e as Error).message} (${url})`) };
  }
  if (!res.ok) {
    let detail = "";
    if (typeof res.text === "function") {
      try {
        detail = await res.text();
      } catch {
        /* ignore body read errors */
      }
    }
    return {
      ok: false,
      result: err(`WorldView API returned HTTP ${res.status} for ${url}${detail ? `: ${detail}` : ""}`),
    };
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  return { ok: true, body };
}

// ---------------------------------------------------------------------------
// Tool: state_at
// ---------------------------------------------------------------------------

export interface StateAtArgs {
  layer: string;
  t: number | string;
  bbox?: string;
  lod?: string;
}

/**
 * As-of-T reconstruction of one layer: `GET /history/:layer?t=&bbox=&lod=`.
 * Returns the GeoJSON FeatureCollection plus a one-line "N features" summary.
 */
export async function stateAt(args: StateAtArgs, deps: Deps): Promise<ToolResult> {
  if (!isLayer(args.layer)) {
    return err(`Invalid layer '${String(args.layer)}'. Must be one of: ${LAYERS.join(", ")}.`);
  }
  const t = toNumber(args.t);
  if (t === null) {
    return err("Parameter 't' (unix seconds) is required and must be numeric.");
  }
  if (args.lod !== undefined && args.lod !== "raw" && args.lod !== "minute") {
    return err("Parameter 'lod' must be 'raw' or 'minute'.");
  }
  const url = buildUrl(deps.apiUrl, `/history/${args.layer}`, {
    t: String(t),
    bbox: args.bbox,
    lod: args.lod,
  });
  const got = await fetchCollection(url, deps);
  if (!got.ok) return got.result;
  const count = got.fc.features?.length ?? 0;
  const summary = `${count} feature${count === 1 ? "" : "s"} in layer '${args.layer}' at t=${t}.`;
  return ok(`${summary}\n${JSON.stringify(got.fc)}`);
}

// ---------------------------------------------------------------------------
// Tool: find_dark_vessels
// ---------------------------------------------------------------------------

export interface FindDarkVesselsArgs {
  t: number | string;
  bbox?: string;
}

/**
 * Dark vessels at time T: pull the `context` layer (`GET /history/context?...`) and keep only
 * features whose `properties.kind === "dark_vessel"` (AIS-gap detections from the backend).
 */
export async function findDarkVessels(args: FindDarkVesselsArgs, deps: Deps): Promise<ToolResult> {
  const t = toNumber(args.t);
  if (t === null) {
    return err("Parameter 't' (unix seconds) is required and must be numeric.");
  }
  const url = buildUrl(deps.apiUrl, "/history/context", {
    t: String(t),
    bbox: args.bbox,
  });
  const got = await fetchCollection(url, deps);
  if (!got.ok) return got.result;
  const dark = (got.fc.features ?? []).filter(
    (f) => f?.properties?.kind === "dark_vessel",
  );
  const fc: FeatureCollection = { type: "FeatureCollection", features: dark };
  const summary = `${dark.length} dark vessel${dark.length === 1 ? "" : "s"} at t=${t}.`;
  return ok(`${summary}\n${JSON.stringify(fc)}`);
}

// ---------------------------------------------------------------------------
// Tool: track_of
// ---------------------------------------------------------------------------

export interface TrackOfArgs {
  layer: string;
  entityId: string;
  from?: number | string;
  to?: number | string;
}

/**
 * One entity's trail: `GET /history/:layer/:entityId/track?from=&to=`.
 * Only adsb/ais/tle expose tracks; `from`/`to` are optional (backend defaults to the last hour).
 */
export async function trackOf(args: TrackOfArgs, deps: Deps): Promise<ToolResult> {
  if (!isTrackLayer(args.layer)) {
    return err(
      `Invalid track layer '${String(args.layer)}'. Tracks exist only for: ${TRACK_LAYERS.join(", ")}.`,
    );
  }
  if (typeof args.entityId !== "string" || args.entityId.trim() === "") {
    return err("Parameter 'entityId' is required.");
  }
  let from: string | undefined;
  let to: string | undefined;
  if (args.from !== undefined) {
    const n = toNumber(args.from);
    if (n === null) return err("Parameter 'from' must be unix seconds (numeric).");
    from = String(n);
  }
  if (args.to !== undefined) {
    const n = toNumber(args.to);
    if (n === null) return err("Parameter 'to' must be unix seconds (numeric).");
    to = String(n);
  }
  const url = buildUrl(
    deps.apiUrl,
    `/history/${args.layer}/${encodeURIComponent(args.entityId)}/track`,
    { from, to },
  );
  const got = await fetchCollection(url, deps);
  if (!got.ok) return got.result;
  const count = got.fc.features?.length ?? 0;
  const summary = `Track for '${args.entityId}' in layer '${args.layer}': ${count} segment${count === 1 ? "" : "s"}.`;
  return ok(`${summary}\n${JSON.stringify(got.fc)}`);
}

// ---------------------------------------------------------------------------
// Tool: list_layers
// ---------------------------------------------------------------------------

/** Static catalogue of the available layers and what each represents. No network call. */
export function listLayers(): ToolResult {
  const lines = LAYERS.map((layer) => {
    const trackable = (TRACK_LAYERS as readonly string[]).includes(layer) ? " [track]" : "";
    return `- ${layer}${trackable}: ${LAYER_DESCRIPTIONS[layer]}`;
  });
  const payload = {
    layers: LAYERS.map((layer) => ({
      layer,
      description: LAYER_DESCRIPTIONS[layer],
      trackable: (TRACK_LAYERS as readonly string[]).includes(layer),
    })),
  };
  return ok(`WorldView layers:\n${lines.join("\n")}\n${JSON.stringify(payload)}`);
}

// ---------------------------------------------------------------------------
// WRITE / async tools (capability-gated — see server.ts dispatch). Each declares the scope a
// capability token must grant; the server enforces it BEFORE invoking the handler, so by the time
// we run here the call is already authorised. The scope constants are exported so the dispatch and
// the tests share one source of truth.
// ---------------------------------------------------------------------------

/** Required capability scope for `watch_aoi`. */
export const WATCH_AOI_SCOPE = "worldview:watch";
/** Required capability scope for `reconstruct_event`. */
export const RECONSTRUCT_EVENT_SCOPE = "worldview:reconstruct";

// ---------------------------------------------------------------------------
// Tool: watch_aoi  (WRITE — creates a watch rule on an area of interest)
// ---------------------------------------------------------------------------

export interface WatchAoiArgs {
  aoiId: string;
  rule: string;
  lead?: number | string;
  /** Capability token; verified by the server before this handler runs. */
  token?: string;
}

/**
 * Create a standing watch rule for an area of interest:
 * `POST {apiUrl}/recon/watch` with `{ aoiId, rule, lead? }`.
 * WRITE/scoped tool (`worldview:watch`). The backend route may not exist yet; a non-2xx degrades
 * to a clear error result. Returns a summary of the created watch (incl. any backend-issued id).
 */
export async function watchAoi(args: WatchAoiArgs, deps: Deps): Promise<ToolResult> {
  if (typeof args.aoiId !== "string" || args.aoiId.trim() === "") {
    return err("Parameter 'aoiId' is required.");
  }
  if (typeof args.rule !== "string" || args.rule.trim() === "") {
    return err("Parameter 'rule' is required.");
  }
  let lead: number | undefined;
  if (args.lead !== undefined) {
    const n = toNumber(args.lead);
    if (n === null) return err("Parameter 'lead' must be numeric (seconds of lead time).");
    lead = n;
  }
  const payload = { aoiId: args.aoiId, rule: args.rule, ...(lead !== undefined ? { lead } : {}) };
  const url = buildUrl(deps.apiUrl, "/recon/watch", {});
  const got = await postJson(url, payload, deps);
  if (!got.ok) return got.result;
  const body = (got.body ?? {}) as Record<string, unknown>;
  const watchId = typeof body.id === "string" ? body.id : typeof body.watchId === "string" ? body.watchId : undefined;
  const summary = `Watch created for AOI '${args.aoiId}' (rule: ${args.rule})${
    watchId ? ` -> watch id ${watchId}` : ""
  }.`;
  return ok(`${summary}\n${JSON.stringify(body)}`);
}

// ---------------------------------------------------------------------------
// Tool: reconstruct_event  (async / long-running — requests a bounded replay)
// ---------------------------------------------------------------------------

export interface ReconstructEventArgs {
  from: number | string;
  to: number | string;
  bbox?: string;
  layers?: string[] | string;
  /** Frame step in seconds (default 60); the backend requires one to bound frame count. */
  stepSeconds?: number | string;
  /** Capability token; verified by the server before this handler runs. */
  token?: string;
}

/**
 * Request a bounded reconstruction/replay over a time window:
 * `POST {apiUrl}/reconstructions` with `{ from, to, stepSeconds, bbox?, layers? }`.
 * WRITE/scoped tool (`worldview:reconstruct`). The backend saves a shareable reconstruction handle
 * (frames re-derive reproducibly from these params); we surface its id so the caller can export it.
 * Non-2xx degrades to a clear error result.
 */
export async function reconstructEvent(args: ReconstructEventArgs, deps: Deps): Promise<ToolResult> {
  const from = toNumber(args.from);
  if (from === null) return err("Parameter 'from' (unix seconds) is required and must be numeric.");
  const to = toNumber(args.to);
  if (to === null) return err("Parameter 'to' (unix seconds) is required and must be numeric.");
  if (to <= from) return err("Parameter 'to' must be greater than 'from'.");

  // `layers` may arrive as an array or a comma-separated string; validate against the known layers.
  let layers: Layer[] | undefined;
  if (args.layers !== undefined) {
    const raw = Array.isArray(args.layers)
      ? args.layers
      : String(args.layers)
          .split(",")
          .map((s) => s.trim())
          .filter((s) => s !== "");
    for (const l of raw) {
      if (!isLayer(l)) {
        return err(`Invalid layer '${String(l)}' in 'layers'. Must be one of: ${LAYERS.join(", ")}.`);
      }
    }
    layers = raw as Layer[];
  }

  // The backend requires a stepSeconds to bound the frame count; default to 60s.
  const stepSeconds = args.stepSeconds !== undefined ? (toNumber(args.stepSeconds) ?? 60) : 60;
  const payload = {
    from,
    to,
    stepSeconds,
    ...(args.bbox !== undefined ? { bbox: args.bbox } : {}),
    ...(layers !== undefined ? { layers } : {}),
  };
  const url = buildUrl(deps.apiUrl, "/reconstructions", {});
  const got = await postJson(url, payload, deps);
  if (!got.ok) return got.result;
  const body = (got.body ?? {}) as Record<string, unknown>;
  // The route returns `{ reconstruction: { id, ... } }`; accept a bare `id`/`jobId` too.
  const recon = (body.reconstruction ?? {}) as Record<string, unknown>;
  const reconId = recon.id ?? body.id ?? body.jobId;
  const jobId = reconId !== undefined && reconId !== null ? String(reconId) : undefined;
  const status = typeof body.status === "string" ? body.status : "accepted";
  const summary = `Reconstruction ${jobId ? `'${jobId}' ` : ""}requested for [${from}, ${to}]${
    layers ? ` over layers ${layers.join(",")}` : ""
  } (status: ${status}).`;
  return ok(`${summary}\n${JSON.stringify(body)}`);
}
