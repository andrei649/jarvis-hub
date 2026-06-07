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

/** Subset of the WHATWG `fetch` we depend on — keeps stubbing trivial in tests. */
export type FetchLike = (
  url: string,
  init?: { method?: string },
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
