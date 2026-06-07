import type { Pool } from "pg";
import { MAX_FEATURES } from "../types.js";

// Recon-window repository (ticket H19.2.2): persist + serve predicted satellite overflights
// of an Area of Interest. The Python predictor writes batches here idempotently (ON CONFLICT
// on the PK), and the API serves upcoming windows + due alerts. Times are UNIX seconds in TS;
// the time columns are timestamptz in SQL (to_timestamp on write, extract(epoch ...) on read).

export interface ReconWindowRow {
  norad_id: number;
  aoi_id: string;
  sensor_type: string;
  t_ingress: number;
  t_peak: number;
  t_egress: number;
  min_distance_km: number;
  sunlit_at_peak: boolean;
  quality: number;
}

export interface InsertBatch {
  sql: string;
  params: unknown[];
}

const COLUMNS =
  "norad_id, aoi_id, sensor_type, t_ingress, t_peak, t_egress, min_distance_km, sunlit_at_peak, quality";

// VALUES template with `?` placeholders, renumbered to $1..$N across the batch. The three
// time columns are wrapped in to_timestamp(...) so UNIX-seconds params land as timestamptz.
const TEMPLATE =
  "?, ?, ?, to_timestamp(?), to_timestamp(?), to_timestamp(?), ?, ?, ?";

const CONFLICT = "ON CONFLICT (norad_id, aoi_id, t_ingress) DO NOTHING";

function rowParams(w: ReconWindowRow): unknown[] {
  return [
    w.norad_id,
    w.aoi_id,
    w.sensor_type,
    w.t_ingress,
    w.t_peak,
    w.t_egress,
    w.min_distance_km,
    w.sunlit_at_peak,
    w.quality,
  ];
}

/** Build a single multi-row INSERT for a batch of windows (pure — unit-testable). */
export function buildReconInsert(windows: ReconWindowRow[]): InsertBatch {
  const valueGroups: string[] = [];
  const params: unknown[] = [];
  let n = 0;
  for (const w of windows) {
    const frag = TEMPLATE.replace(/\?/g, () => `$${++n}`);
    valueGroups.push(`(${frag})`);
    params.push(...rowParams(w));
  }
  const sql = `INSERT INTO recon_windows (${COLUMNS}) VALUES ${valueGroups.join(", ")} ${CONFLICT}`;
  return { sql, params };
}

// Read projection: extract the time columns back to UNIX seconds.
const SELECT_COLUMNS = `
  norad_id, aoi_id, sensor_type,
  extract(epoch FROM t_ingress) AS t_ingress,
  extract(epoch FROM t_peak)    AS t_peak,
  extract(epoch FROM t_egress)  AS t_egress,
  min_distance_km, sunlit_at_peak, quality`;

function toRow(r: Record<string, unknown>): ReconWindowRow {
  return {
    norad_id: Number(r.norad_id),
    aoi_id: String(r.aoi_id),
    sensor_type: String(r.sensor_type),
    t_ingress: Number(r.t_ingress),
    t_peak: Number(r.t_peak),
    t_egress: Number(r.t_egress),
    min_distance_km: Number(r.min_distance_km),
    sunlit_at_peak: Boolean(r.sunlit_at_peak),
    quality: Number(r.quality),
  };
}

/**
 * Insert a batch with one query; on failure, fall back to per-row inserts so a single poison
 * row can't drop the whole batch. Mirrors historyWriter's idempotent at-least-once pattern.
 */
export async function upsertWindows(pool: Pool, windows: ReconWindowRow[]): Promise<number> {
  if (windows.length === 0) return 0;
  try {
    const { sql, params } = buildReconInsert(windows);
    return (await pool.query(sql, params)).rowCount ?? 0;
  } catch {
    let written = 0;
    for (const w of windows) {
      try {
        const { sql, params } = buildReconInsert([w]);
        written += (await pool.query(sql, params)).rowCount ?? 0;
      } catch {
        // Skip the offending row; the rest of the batch still lands.
      }
    }
    return written;
  }
}

/** Windows ingressing in [from, to] (optionally one AOI), ordered by ingress time. */
export async function upcomingWindows(
  pool: Pool,
  { aoiId, from, to }: { aoiId?: string; from: number; to: number },
): Promise<ReconWindowRow[]> {
  const params: unknown[] = [from, to];
  let aoiClause = "";
  if (aoiId) {
    params.push(aoiId);
    aoiClause = ` AND aoi_id = $${params.length}`;
  }
  const sql = `
    SELECT ${SELECT_COLUMNS}
    FROM recon_windows
    WHERE t_ingress BETWEEN to_timestamp($1) AND to_timestamp($2)${aoiClause}
    ORDER BY t_ingress ASC
    LIMIT ${MAX_FEATURES}`;
  const res = await pool.query(sql, params);
  return res.rows.map(toRow);
}

/** Windows whose ingress falls in [now, now+leadSeconds] — the alertable set. */
export async function dueAlerts(
  pool: Pool,
  { now, leadSeconds }: { now: number; leadSeconds: number },
): Promise<ReconWindowRow[]> {
  const sql = `
    SELECT ${SELECT_COLUMNS}
    FROM recon_windows
    WHERE t_ingress BETWEEN to_timestamp($1) AND to_timestamp($2)
    ORDER BY t_ingress ASC
    LIMIT ${MAX_FEATURES}`;
  const res = await pool.query(sql, [now, now + leadSeconds]);
  return res.rows.map(toRow);
}
