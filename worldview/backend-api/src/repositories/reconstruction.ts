import type { Pool } from "pg";
import { recordAction } from "./ontologyAudit.js";
import { HISTORY_BY_LAYER } from "./history.js";
import { isLayer, type BBox, type FeatureCollection, type Layer, type Lod } from "../types.js";

// Reconstruction repository (tickets H19.2.7 "Event reconstruction + shareable replay export" and
// H19.4.6 "Export / reporting"). A RECONSTRUCTION is a temporally-bounded, viewport-bounded request to
// re-derive layered as-of-T frames from the history hypertables. We SAVE only the params (the shareable
// handle in db/schema/13_reconstructions.sql) and RE-DERIVE the frames on demand: buildFrames steps
// from..to by stepSeconds and, for each frame timestamp, calls the EXISTING history as-of-T readers
// (flightsAsOf/vesselsAsOf/... via HISTORY_BY_LAYER) for each requested layer. This is what makes a
// reconstruction REPRODUCIBLE — the same params always produce the same frame timestamps and the same
// as-of-T reads; we never freeze a copy. Creating a reconstruction is appended to the tamper-evident
// ontology_actions hash chain (objectType 'Reconstruction') via recordAction, so the saved handle is
// auditable. Times are UNIX seconds (UTC instants) everywhere, matching the rest of the API. All SQL is
// parameterized; reads degrade to []/null on a missing table (Postgres 42P01) like the rest of the API.

// Postgres "undefined_table" — the reconstructions table isn't applied yet. Reads degrade to []/null;
// the create write re-throws (a saved handle MUST surface a missing table).
const UNDEFINED_TABLE = "42P01";

// The audited object type for the hash chain (mirrors Case/ontology actions).
const RECONSTRUCTION_OBJECT_TYPE = "Reconstruction";

// FRAME-COUNT CAP. buildFrames steps from..to by stepSeconds; an unbounded range / tiny step would
// produce a runaway number of frames (each frame is N as-of-T queries). We cap the number of frames a
// single reconstruction can produce so the export stays bounded and portable. ~600 frames at a sane
// cadence is plenty for a replay timeline; ranges that would exceed the cap are rejected at create time
// and (defensively) truncated in buildFrames.
export const MAX_FRAMES = 600;

// Sanity bounds on the step so a 0/negative/huge step can't be saved.
const MIN_STEP_SECONDS = 1;
const MAX_STEP_SECONDS = 86_400; // one day

const DAY_SECONDS = 86_400;

// RETENTION HORIZONS (seconds) — MUST mirror the per-layer add_retention_policy() windows in
// db/schema/07_policies.sql, which DROP raw chunks older than these. The default `raw`-LOD as-of-T
// readers (history.ts) query ONLY the raw hypertable, so a reconstruction with a frame T older than
// the layer's horizon would silently return EMPTY frames once the raw chunks are dropped. The minute
// continuous aggregates (adsb_positions_1m / ais_positions_1m) are SEPARATE hypertables that survive
// retention, so for frames older than the horizon we route those layers to the "minute" LOD (which
// reads the surviving cagg) instead of returning empty raw results. Only adsb/ais have a minute cagg
// path in history.ts; layers without one keep "raw" (the lod arg is ignored there anyway). Keep these
// in sync with 07_policies.sql (review CRITICAL: retention vs reconstruction).
const RETENTION_HORIZON_SECONDS: Partial<Record<Layer, number>> = {
  adsb: 90 * DAY_SECONDS,
  ais: 180 * DAY_SECONDS,
};

// Pick the LOD for reading `layer` at frame time `t`: route reads OLDER than the layer's retention
// horizon (relative to `nowSeconds`) to "minute" (the surviving cagg), else "raw". Layers without a
// horizon/cagg always read "raw". Pure so buildFrames + tests can reason about it deterministically.
export function lodForFrame(layer: Layer, t: number, nowSeconds: number): Lod {
  const horizon = RETENTION_HORIZON_SECONDS[layer];
  if (horizon !== undefined && t < nowSeconds - horizon) return "minute";
  return "raw";
}

export interface ReconstructionParams {
  from: number;
  to: number;
  stepSeconds: number;
  bbox?: BBox | null;
  layers: Layer[];
}

export interface ReconstructionRow {
  id: number;
  title: string | null;
  params: ReconstructionParams;
  createdBy: string | null;
  createdAt: number;
}

// One re-derived frame: a frame timestamp + the as-of-T FeatureCollection per requested layer.
export interface Frame {
  t: number;
  layers: Record<string, FeatureCollection>;
}

/**
 * Validate raw reconstruction params into a normalized ReconstructionParams, or return an error string.
 * Pure (no DB): from<to, a sane step, at least one known layer, an optional well-formed bbox, and a
 * frame count within MAX_FRAMES. Reused by createReconstruction and exposed for the route to 400 early.
 */
export function validateParams(
  raw: Record<string, unknown>,
): { params: ReconstructionParams } | { error: string } {
  const from = Number(raw.from);
  const to = Number(raw.to);
  if (!Number.isFinite(from) || !Number.isFinite(to)) {
    return { error: "'from' and 'to' (unix seconds) are required numbers" };
  }
  if (from >= to) return { error: "'from' must be strictly before 'to'" };

  const stepSeconds = Number(raw.stepSeconds);
  if (!Number.isFinite(stepSeconds) || stepSeconds < MIN_STEP_SECONDS || stepSeconds > MAX_STEP_SECONDS) {
    return { error: `'stepSeconds' must be between ${MIN_STEP_SECONDS} and ${MAX_STEP_SECONDS}` };
  }

  const rawLayers = Array.isArray(raw.layers) ? raw.layers : [];
  const layers = rawLayers.filter((l): l is Layer => typeof l === "string" && isLayer(l));
  if (layers.length === 0) {
    return { error: "'layers' must contain at least one known layer (adsb/ais/tle/ew/context)" };
  }

  const bbox = parseBBoxParam(raw.bbox);
  if (bbox === undefined) return { error: "'bbox' must be {w,s,e,n} numbers when present" };

  // Reject ranges that would exceed the frame cap up front (don't save an un-exportable handle).
  const count = frameCount(from, to, stepSeconds);
  if (count > MAX_FRAMES) {
    return {
      error: `range/step would produce ${count} frames; cap is ${MAX_FRAMES} (widen step or narrow range)`,
    };
  }

  return { params: { from, to, stepSeconds, bbox: bbox ?? null, layers } };
}

// Accept a bbox as either a {w,s,e,n} object (jsonb round-trips this) OR a "w,s,e,n" comma string
// (the form /history, /live, and the MCP reconstruct_event tool use) — returns the BBox, null when
// absent, or `undefined` to signal a malformed bbox (so the caller can 400).
function parseBBoxParam(raw: unknown): BBox | null | undefined {
  if (raw == null) return null;
  // "w,s,e,n" string form — unify with the rest of the stack's bbox convention.
  if (typeof raw === "string") {
    const parts = raw.split(",").map(Number);
    if (parts.length !== 4 || parts.some((v) => !Number.isFinite(v))) return undefined;
    const [w, s, e, n] = parts as [number, number, number, number];
    return { w, s, e, n };
  }
  if (typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const o = raw as Record<string, unknown>;
  const w = Number(o.w);
  const s = Number(o.s);
  const e = Number(o.e);
  const n = Number(o.n);
  if ([w, s, e, n].some((v) => !Number.isFinite(v))) return undefined;
  return { w, s, e, n };
}

// How many frame timestamps does stepping from..to by stepSeconds produce (inclusive of `from`, and
// of `to` only when it lands exactly on a step)? Pure + cheap so validate can pre-check the cap.
function frameCount(from: number, to: number, stepSeconds: number): number {
  return Math.floor((to - from) / stepSeconds) + 1;
}

/**
 * Save a reconstruction (the shareable handle) and append a `reconstruction.create` audit row. Validates
 * params first (from<to, sane step/layers/bbox, within the frame cap); throws on invalid params so the
 * route can 400. The frames are NOT stored — only the params, which re-derive the frames on export.
 */
export async function createReconstruction(
  pool: Pool,
  {
    title,
    params,
    actor,
  }: { title?: string | null; params: Record<string, unknown>; actor: string | null },
): Promise<ReconstructionRow> {
  const checked = validateParams(params);
  if ("error" in checked) {
    throw new Error(checked.error);
  }
  const sql = `
    INSERT INTO reconstructions (title, params, created_by)
    VALUES ($1, $2::jsonb, $3)
    RETURNING id, title, params, created_by, extract(epoch FROM created_at) AS created_at`;
  const res = await pool.query(sql, [
    title ?? null,
    JSON.stringify(checked.params),
    actor ?? null,
  ]);
  const row = toReconstructionRow(res.rows[0] as Record<string, unknown>);

  await recordAction(pool, {
    actor,
    objectType: RECONSTRUCTION_OBJECT_TYPE,
    objectId: String(row.id),
    action: "reconstruction.create",
    params: { title: title ?? null, ...checked.params },
  });
  return row;
}

/** One reconstruction by id, or null when absent / table missing. */
export async function getReconstruction(pool: Pool, id: number): Promise<ReconstructionRow | null> {
  const sql = `
    SELECT id, title, params, created_by, extract(epoch FROM created_at) AS created_at
    FROM reconstructions
    WHERE id = $1`;
  try {
    const res = await pool.query(sql, [id]);
    const row = res.rows[0];
    return row ? toReconstructionRow(row as Record<string, unknown>) : null;
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return null;
  }
}

/** List reconstructions, newest first, capped. Degrades to [] on a missing table. */
export async function listReconstructions(pool: Pool): Promise<ReconstructionRow[]> {
  const sql = `
    SELECT id, title, params, created_by, extract(epoch FROM created_at) AS created_at
    FROM reconstructions
    ORDER BY created_at DESC, id DESC
    LIMIT ${MAX_FRAMES}`;
  try {
    const res = await pool.query(sql);
    return res.rows.map((r) => toReconstructionRow(r as Record<string, unknown>));
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return [];
  }
}

/**
 * Re-derive the replay frames for a reconstruction's params. Steps the timeline from `from` to `to` by
 * `stepSeconds` (inclusive of `from`; `to` is included only when it lands on a step) and, for EACH frame
 * timestamp, calls the EXISTING history as-of-T reader (HISTORY_BY_LAYER) for EACH requested layer —
 * reusing the same `DISTINCT ON ... WHERE ts <= to_timestamp($1)` reconstruction the /history route
 * serves, so we never reinvent as-of-T. The result is `[{ t, layers: { adsb: FeatureCollection, ... } }]`.
 *
 * The frame count is BOUNDED at MAX_FRAMES (validateParams rejects over-cap ranges at create time; we
 * also truncate defensively here so a directly-built params object can't run away). Reads are issued per
 * layer per frame; a 42P01 inside a reader already degrades to an empty collection there.
 *
 * RETENTION-AWARE LOD. Raw chunks older than a layer's retention horizon (07_policies.sql) are dropped,
 * so a frame T older than that horizon is routed to the "minute" LOD (the surviving continuous
 * aggregate) instead of returning empty raw results — see lodForFrame / RETENTION_HORIZON_SECONDS.
 */
export async function buildFrames(pool: Pool, params: ReconstructionParams): Promise<Frame[]> {
  const { from, to, stepSeconds, bbox, layers } = params;
  // Single `now` for the whole build so every frame's retention decision is consistent (and tests
  // can pin it). buildFrames is invoked at export time, so "now" is the request instant.
  const nowSeconds = Date.now() / 1000;
  const frames: Frame[] = [];
  for (let t = from; t <= to && frames.length < MAX_FRAMES; t += stepSeconds) {
    const layerEntries: Record<string, FeatureCollection> = {};
    for (const layer of layers) {
      const reader = HISTORY_BY_LAYER[layer];
      layerEntries[layer] = await reader(pool, t, bbox ?? null, lodForFrame(layer, t, nowSeconds));
    }
    frames.push({ t, layers: layerEntries });
  }
  return frames;
}

function toReconstructionRow(r: Record<string, unknown>): ReconstructionRow {
  return {
    id: Number(r.id),
    title: r.title == null ? null : String(r.title),
    params: normalizeStoredParams(r.params),
    createdBy: r.created_by == null ? null : String(r.created_by),
    createdAt: Number(r.created_at),
  };
}

// jsonb comes back parsed by `pg`; coerce defensively (guard the implicit parse like the rest of the
// code does) and re-validate into the typed shape so a hand-edited row can't break buildFrames.
function normalizeStoredParams(v: unknown): ReconstructionParams {
  let obj: Record<string, unknown>;
  if (v == null) obj = {};
  else if (typeof v === "string") {
    try {
      obj = JSON.parse(v) as Record<string, unknown>;
    } catch {
      obj = {};
    }
  } else obj = v as Record<string, unknown>;
  const checked = validateParams(obj);
  if ("params" in checked) return checked.params;
  // Stored row failed re-validation (shouldn't happen — create validates) — surface a safe empty shape.
  return {
    from: Number(obj.from) || 0,
    to: Number(obj.to) || 0,
    stepSeconds: Number(obj.stepSeconds) || MIN_STEP_SECONDS,
    bbox: parseBBoxParam(obj.bbox) ?? null,
    layers: (Array.isArray(obj.layers) ? obj.layers : []).filter(
      (l): l is Layer => typeof l === "string" && isLayer(l),
    ),
  };
}
