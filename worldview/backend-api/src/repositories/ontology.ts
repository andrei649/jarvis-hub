import type { Pool } from "pg";
import {
  getObjectSpec,
  LINK_TYPES,
  type ObjectTypeSpec,
  type OntologyLink,
  type OntologyObject,
} from "../ontology/registry.js";
import { MAX_FEATURES } from "../types.js";

// Ontology projection repository (ticket H19.4.1). Reads the relational System-of-Record and emits
// the ontology graph: Objects (listObjects/getObject) and Links (linksOf). All SQL is parameterized;
// the dim-stream object types reuse the as-of-T `DISTINCT ON (id) ... ORDER BY id, ts DESC` latest-
// state shape from history.ts/provenance.ts, and every query degrades gracefully on a missing table
// (Postgres 42P01) the way history.ts does — so the ontology still answers on a partially-applied
// schema or plain Postgres. Times are UNIX seconds (extract(epoch ...) on read), matching the rest
// of the API.

// Postgres "undefined_table" — a backing table is absent (plain Postgres / schema not applied). We
// degrade to an empty projection rather than throwing, mirroring history.ts/provenance.ts.
const UNDEFINED_TABLE = "42P01";

const DEFAULT_LIMIT = 500;

function clampLimit(limit: number | undefined): number {
  if (!limit || Number.isNaN(limit) || limit <= 0) return DEFAULT_LIMIT;
  return Math.min(Math.floor(limit), MAX_FEATURES);
}

/** Coerce a path/id param the way the writers do: numeric ids (mmsi/norad_id) become numbers. */
function coerceId(spec: ObjectTypeSpec, id: string): string | number | null {
  if (!spec.numericId) return id;
  const n = Number(id);
  return Number.isNaN(n) ? null : n;
}

// Build the SELECT for a "dim-stream" object type: the catalog dim LEFT JOINed to the LATEST stream
// row per id (LATERAL DISTINCT ON ... ORDER BY ts DESC), plus the stream's provenance columns. A
// LEFT JOIN keeps dim rows that have no stream fix yet (their provenance is null). `whereId` adds an
// optional `WHERE d.<id> = $1` for getObject; listObjects passes "".
function dimStreamSql(spec: ObjectTypeSpec, whereId: boolean): string {
  const cols = spec.selectColumns.join(",\n      ");
  const where = whereId ? `\n    WHERE d.${spec.idColumn} = $1` : "";
  const limit = whereId ? "" : "\n    LIMIT $1";
  return `
    SELECT
      ${cols},
      s.source AS __source,
      extract(epoch FROM s.ts) AS __ts,
      extract(epoch FROM s.ingested_at) AS __ingested_at
    FROM ${spec.table} d
    LEFT JOIN LATERAL (
      SELECT * FROM ${spec.streamTable}
      WHERE ${spec.streamTable}.${spec.streamIdColumn} = d.${spec.idColumn}
      ORDER BY ts DESC
      LIMIT 1
    ) s ON true${where}
    ORDER BY d.${spec.idColumn}${limit}`;
}

// Build the SELECT for a single "table" object type. For provenance-bearing table types the
// spec.selectColumns already alias the lineage columns (`source`, `... AS ts`, `... AS ingested_at`),
// so toObject reads them directly — no __-prefixed columns needed here. `whereId` filters on the
// (possibly composite-expression) idColumn for getObject; the first select item is always the
// synthetic/natural `id`, so ORDER BY 1 gives a stable order.
function tableSql(spec: ObjectTypeSpec, whereId: boolean): string {
  const cols = spec.selectColumns.join(",\n      ");
  const where = whereId ? `\n    WHERE (${spec.idColumn}) = $1` : "";
  const limit = whereId ? "" : "\n    LIMIT $1";
  return `
    SELECT
      ${cols}
    FROM ${spec.table}${where}
    ORDER BY 1${limit}`;
}

// Map a projected DB row into the canonical OntologyObject JSON. Provenance is read from the __source/
// __ts/__ingested_at columns (dim-stream) or the spec's ts/source/ingested_at aliases (table types).
function toObject(spec: ObjectTypeSpec, row: Record<string, unknown>): OntologyObject {
  const source =
    row.__source != null ? String(row.__source) : row.source != null ? String(row.source) : null;
  const ts = row.__ts != null ? Number(row.__ts) : row.ts != null ? Number(row.ts) : null;
  const ingestedAt =
    row.__ingested_at != null
      ? Number(row.__ingested_at)
      : row.ingested_at != null
        ? Number(row.ingested_at)
        : null;
  return {
    id: String(row.id ?? row[spec.idColumn] ?? ""),
    type: spec.type,
    title: spec.title(row),
    properties: spec.properties(row),
    provenance: {
      source: spec.hasProvenance ? source : null,
      ts: spec.hasProvenance ? ts : null,
      ingestedAt: spec.hasProvenance ? ingestedAt : null,
    },
  };
}

async function runOrEmpty(
  pool: Pool,
  sql: string,
  params: unknown[],
): Promise<Record<string, unknown>[]> {
  try {
    const res = await pool.query(sql, params);
    return res.rows;
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return []; // backing table absent on this deployment — degrade like history.ts
  }
}

/** List objects of one type (latest state), newest dim-id first, capped at `limit`. */
export async function listObjects(
  pool: Pool,
  type: string,
  { limit }: { limit?: number } = {},
): Promise<OntologyObject[]> {
  const spec = getObjectSpec(type);
  if (!spec) return [];
  const sql = spec.kind === "dim-stream" ? dimStreamSql(spec, false) : tableSql(spec, false);
  const rows = await runOrEmpty(pool, sql, [clampLimit(limit)]);
  return rows.map((r) => toObject(spec, r));
}

/** One object of `type` by id, or null when absent / id-coercion fails / table missing. */
export async function getObject(
  pool: Pool,
  type: string,
  id: string,
): Promise<OntologyObject | null> {
  const spec = getObjectSpec(type);
  if (!spec) return null;
  const idValue = coerceId(spec, id);
  if (idValue === null) return null;
  const sql = spec.kind === "dim-stream" ? dimStreamSql(spec, true) : tableSql(spec, true);
  const rows = await runOrEmpty(pool, sql, [idValue]);
  const row = rows[0];
  return row ? toObject(spec, row) : null;
}

// ---------------------------------------------------------------------------
// LINK PROJECTIONS — one parameterized arm per link resolver. Each returns the edges incident to the
// given object (as `from` for that resolver's link type). Small, real, FK-derived edges.
// ---------------------------------------------------------------------------

// Satellite -covers-> Aoi: every recon_window for this norad_id is an edge to its aoi_id.
async function satCoversAoi(pool: Pool, noradId: string): Promise<OntologyLink[]> {
  const n = Number(noradId);
  if (Number.isNaN(n)) return [];
  const sql = `
    SELECT aoi_id,
           extract(epoch FROM t_ingress) AS t_ingress,
           extract(epoch FROM t_peak)    AS t_peak,
           extract(epoch FROM t_egress)  AS t_egress,
           min_distance_km, quality
    FROM recon_windows
    WHERE norad_id = $1
    ORDER BY t_ingress ASC
    LIMIT ${MAX_FEATURES}`;
  const rows = await runOrEmpty(pool, sql, [n]);
  return rows.map((r) => ({
    type: "covers",
    fromType: "Satellite",
    fromId: String(n),
    toType: "Aoi",
    toId: String(r.aoi_id),
    properties: {
      tIngress: Number(r.t_ingress),
      tPeak: Number(r.t_peak),
      tEgress: Number(r.t_egress),
      minDistanceKm: Number(r.min_distance_km),
      quality: Number(r.quality),
    },
  }));
}

// Vessel -wentDark-> DarkVesselEvent: each dark_vessel_event for this mmsi is an edge to the event.
async function vesselWentDark(pool: Pool, mmsi: string): Promise<OntologyLink[]> {
  const n = Number(mmsi);
  if (Number.isNaN(n)) return [];
  // Select the canonical DarkVesselEvent id expression (mmsi || ':' || full epoch) directly in SQL so
  // the edge's toId is byte-identical to the object's `id` — no JS/Postgres float-format drift, and no
  // rounding (the ::bigint that broke fractional-second timestamps is gone everywhere).
  const sql = `
    SELECT geofence_id, gap_seconds, status,
           extract(epoch FROM ts) AS ts,
           (mmsi || ':' || extract(epoch FROM ts)) AS event_id
    FROM dark_vessel_events
    WHERE mmsi = $1
    ORDER BY ts DESC
    LIMIT ${MAX_FEATURES}`;
  const rows = await runOrEmpty(pool, sql, [n]);
  return rows.map((r) => ({
    type: "wentDark",
    fromType: "Vessel",
    fromId: String(n),
    toType: "DarkVesselEvent",
    toId: String(r.event_id),
    properties: {
      geofenceId: String(r.geofence_id),
      gapSeconds: Number(r.gap_seconds),
      status: String(r.status),
      ts: Number(r.ts),
    },
  }));
}

// DarkVesselEvent -inGeofence-> Aoi: the event's geofence_id FK is the single edge to its AOI. The
// event id is the synthetic "mmsi:ts(epoch)". We prefilter on the indexed mmsi (the part before the
// first ':') for efficiency, then match the FULL canonical id expression — never reconstructing the
// timestamp via to_timestamp/float equality, which rounding+format drift made unreliable.
async function darkInGeofence(pool: Pool, eventId: string): Promise<OntologyLink[]> {
  const mmsi = Number(eventId.split(":")[0]);
  if (Number.isNaN(mmsi)) return [];
  const sql = `
    SELECT geofence_id
    FROM dark_vessel_events
    WHERE mmsi = $1 AND (mmsi || ':' || extract(epoch FROM ts)) = $2
    LIMIT 1`;
  const rows = await runOrEmpty(pool, sql, [mmsi, eventId]);
  const row = rows[0];
  if (!row) return [];
  return [
    {
      type: "inGeofence",
      fromType: "DarkVesselEvent",
      fromId: eventId,
      toType: "Aoi",
      toId: String(row.geofence_id),
      properties: {},
    },
  ];
}

/**
 * All links incident to `(type, id)` as the `from` side: every registered link type whose fromType
 * matches `type` is resolved and its edges concatenated. Unknown types / no edges ⇒ []. This is the
 * read side of the graph that GET /ontology/objects/:type/:id/links serves.
 */
export async function linksOf(pool: Pool, type: string, id: string): Promise<OntologyLink[]> {
  if (!getObjectSpec(type)) return [];
  const links: OntologyLink[] = [];
  for (const link of LINK_TYPES) {
    if (link.fromType !== type) continue;
    if (link.resolver === "satCoversAoi") links.push(...(await satCoversAoi(pool, id)));
    else if (link.resolver === "vesselWentDark") links.push(...(await vesselWentDark(pool, id)));
    else if (link.resolver === "darkInGeofence") links.push(...(await darkInGeofence(pool, id)));
  }
  return links;
}
