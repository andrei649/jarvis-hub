import type { Pool } from "pg";

// Provenance / chain-of-custody repository (ticket H19.4.3). Given a (layer, entity) it returns
// the lineage of the LAST-KNOWN datum at or before T: where it came from (`source`), WHEN it was
// true in the world (valid time = the row's `ts`), and WHEN WorldView recorded it (transaction
// time = `ingested_at`). This is the two-axis bitemporal model documented in
// db/schema/10_provenance.sql. Times are UNIX seconds in TS; timestamptz in SQL (to_timestamp on
// the bound T, extract(epoch ...) on read — both UTC, matching history.ts).

export interface Provenance {
  layer: string;
  entityId: string;
  source: string;
  /** Valid time: the event's `ts` (when it was true in the world), UNIX seconds. */
  ts: number;
  /** Transaction time: when WorldView recorded the datum (`ingested_at`), UNIX seconds. */
  ingestedAt: number;
}

// Postgres "undefined_table" — the stream table isn't present (e.g. plain Postgres / a layer's
// schema not applied). Provenance degrades to null rather than throwing, mirroring history.ts.
const UNDEFINED_TABLE = "42P01";

// Per-layer lookup: the stream table, its entity-id column, and whether that id is numeric (so we
// coerce the path param the way the writers do — mmsi/norad_id are numbers, icao24/h3_index/
// event_id are text). The entity columns mirror history.ts's TRACK_TABLES + the provenance_latest
// view in 10_provenance.sql.
interface LayerSpec {
  table: string;
  idColumn: string;
  numericId: boolean;
}

const LAYER_SPECS: Record<string, LayerSpec> = {
  adsb: { table: "adsb_positions", idColumn: "icao24", numericId: false },
  ais: { table: "ais_positions", idColumn: "mmsi", numericId: true },
  tle: { table: "satellite_ephemeris", idColumn: "norad_id", numericId: true },
  ew: { table: "gps_jamming", idColumn: "h3_index", numericId: false },
  context: { table: "geopolitical_events", idColumn: "event_id", numericId: false },
};

/** Layers for which a chain-of-custody lookup is supported (matches /provenance route validation). */
export const PROVENANCE_LAYERS = Object.keys(LAYER_SPECS);

export function isProvenanceLayer(layer: string): boolean {
  return layer in LAYER_SPECS;
}

/**
 * Chain-of-custody of the last-known datum for `entityId` in `layer`, at or before T (defaults to
 * now). Same DISTINCT-ON shape as the as-of-T history queries: pick the most recent row with
 * `ts <= to_timestamp($1)`, parameterized. Returns null when the entity has no datum at/<=T (or
 * the layer is unknown / its table is absent).
 */
export async function provenanceOf(
  pool: Pool,
  layer: string,
  entityId: string,
  t: number = Date.now() / 1000,
): Promise<Provenance | null> {
  const spec = LAYER_SPECS[layer];
  if (!spec) return null;

  const idValue: string | number = spec.numericId ? Number(entityId) : entityId;
  if (spec.numericId && Number.isNaN(idValue as number)) return null;

  const sql = `
    SELECT ${spec.idColumn} AS entity_id, source,
           extract(epoch FROM ts) AS ts,
           extract(epoch FROM ingested_at) AS ingested_at
    FROM ${spec.table}
    WHERE ${spec.idColumn} = $1 AND ts <= to_timestamp($2)
    ORDER BY ${spec.idColumn}, ts DESC
    LIMIT 1`;

  let row: Record<string, unknown> | undefined;
  try {
    const res = await pool.query(sql, [idValue, t]);
    row = res.rows[0];
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return null; // table absent on this deployment — degrade gracefully like history.ts
  }
  if (!row) return null;

  return {
    layer,
    entityId: String(row.entity_id),
    source: String(row.source),
    ts: Number(row.ts),
    ingestedAt: Number(row.ingested_at),
  };
}
