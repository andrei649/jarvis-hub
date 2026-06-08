import type { Pool } from "pg";
import { historyRowsWrittenTotal } from "../metrics/registry.js";

// History writer (design doc §4.4): batches normalized envelopes into the right TimescaleDB
// hypertable. Idempotent on the PK (ON CONFLICT DO NOTHING), so at-least-once Kafka delivery
// is safe. Geometry is built in-DB from lon/lat/alt or the envelope's geom_wkt.

export interface Envelope {
  domain: string;
  source: string;
  entity_id: string;
  ts: number;
  lon?: number | null;
  lat?: number | null;
  alt_m?: number | null;
  geom_wkt?: string | null;
  payload?: Record<string, unknown>;
}

export interface InsertBatch {
  sql: string;
  params: unknown[];
}

interface DomainSpec {
  table: string;
  columns: string;
  // VALUES template with `?` placeholders, renumbered to $1..$N across the batch.
  template: string;
  conflict: string;
  params: (env: Envelope) => unknown[];
}

const p = (env: Envelope) => env.payload ?? {};

// Each spec's `template` has exactly as many `?` as its `params` returns, in the same order.
const ADSB: DomainSpec = {
  table: "adsb_positions",
  columns:
    "ts, icao24, geom, alt_m, gs_kt, track_deg, vert_rate_fpm, callsign, squawk, on_ground, is_military, source",
  template:
    "to_timestamp(?), ?, ST_SetSRID(ST_MakePoint(?,?,?),4326), ?,?,?,?,?,?,?,?,?",
  conflict: "ON CONFLICT (icao24, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      env.entity_id,
      env.lon,
      env.lat,
      env.alt_m ?? 0,
      env.alt_m ?? null,
      d.gs_kt ?? null,
      d.track_deg ?? null,
      d.vert_rate_fpm ?? null,
      d.callsign ?? null,
      d.squawk ?? null,
      d.on_ground ?? false,
      d.is_military ?? false,
      env.source,
    ];
  },
};

const AIS: DomainSpec = {
  table: "ais_positions",
  columns: "ts, mmsi, geom, sog_kt, cog_deg, heading_deg, nav_status, source",
  template: "to_timestamp(?), ?, ST_SetSRID(ST_MakePoint(?,?),4326), ?,?,?,?,?",
  conflict: "ON CONFLICT (mmsi, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      Number(env.entity_id),
      env.lon,
      env.lat,
      d.sog_kt ?? null,
      d.cog_deg ?? null,
      d.heading_deg ?? null,
      d.nav_status ?? null,
      env.source,
    ];
  },
};

const TLE: DomainSpec = {
  table: "satellite_ephemeris",
  columns: "ts, norad_id, geom, velocity_kms, sensor_type, footprint, is_sunlit",
  template:
    "to_timestamp(?), ?, ST_SetSRID(ST_MakePoint(?,?,?),4326), ?, ?, ST_GeomFromText(?,4326), ?",
  conflict: "ON CONFLICT (norad_id, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      Number(env.entity_id),
      env.lon,
      env.lat,
      env.alt_m ?? 0,
      d.velocity_kms ?? null,
      d.sensor_type ?? "optical",
      env.geom_wkt ?? null,
      d.is_sunlit ?? null,
    ];
  },
};

const EW: DomainSpec = {
  table: "gps_jamming",
  columns: "ts, h3_index, h3_resolution, h3_geom, intensity, sample_count, source",
  template: "to_timestamp(?), ?, ?, ST_GeomFromText(?,4326), ?, ?, ?",
  conflict: "ON CONFLICT (h3_index, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      env.entity_id,
      d.h3_resolution ?? 5,
      env.geom_wkt ?? null,
      d.intensity ?? 0,
      d.sample_count ?? 0,
      env.source,
    ];
  },
};

// Context envelopes carry a `kind` and route to different tables.
const DARK_VESSEL: DomainSpec = {
  table: "dark_vessel_events",
  columns:
    "ts, mmsi, geofence_id, last_seen_ts, last_seen_geom, gap_seconds, extrapolated_geom, status",
  template:
    "to_timestamp(?), ?, ?, to_timestamp(?), ST_SetSRID(ST_MakePoint(?,?),4326), ?, ST_SetSRID(ST_MakePoint(?,?),4326), ?",
  conflict: "ON CONFLICT (mmsi, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      d.mmsi ?? Number(env.entity_id),
      d.geofence_id ?? null,
      d.last_seen_ts ?? env.ts,
      d.last_lon ?? env.lon,
      d.last_lat ?? env.lat,
      d.gap_seconds ?? 0,
      env.lon,
      env.lat,
      d.status ?? "dark",
    ];
  },
};

const EVENT: DomainSpec = {
  table: "geopolitical_events",
  columns: "ts, event_id, category, severity, geom, source, metadata",
  template:
    "to_timestamp(?), ?, ?, ?, COALESCE(ST_GeomFromText(?,4326), ST_SetSRID(ST_MakePoint(?,?),4326)), ?, ?",
  conflict: "ON CONFLICT (event_id, ts) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.ts,
      env.entity_id,
      d.category ?? "event",
      d.severity ?? 1,
      env.geom_wkt ?? null,
      env.lon,
      env.lat,
      env.source,
      JSON.stringify(d),
    ];
  },
};

const NOTAM: DomainSpec = {
  table: "notams",
  columns: "id, notam_type, effective_from, effective_to, geom, source",
  template: "?, ?, to_timestamp(?), to_timestamp(?), ST_GeomFromText(?,4326), ?",
  conflict: "ON CONFLICT (id) DO NOTHING",
  params: (env) => {
    const d = p(env);
    return [
      env.entity_id,
      d.notam_type ?? null,
      d.effective_from ?? env.ts,
      d.effective_to ?? null,
      env.geom_wkt ?? null,
      env.source,
    ];
  },
};

const SIMPLE_SPECS: Record<string, DomainSpec> = { adsb: ADSB, ais: AIS, tle: TLE, ew: EW };

/** Build a single multi-row INSERT for a homogeneous batch (pure — unit-testable). */
export function buildBatchInsert(spec: DomainSpec, envelopes: Envelope[]): InsertBatch {
  const valueGroups: string[] = [];
  const params: unknown[] = [];
  let n = 0;
  for (const env of envelopes) {
    const rowParams = spec.params(env);
    const frag = spec.template.replace(/\?/g, () => `$${++n}`);
    valueGroups.push(`(${frag})`);
    params.push(...rowParams);
  }
  const sql = `INSERT INTO ${spec.table} (${spec.columns}) VALUES ${valueGroups.join(", ")} ${spec.conflict}`;
  return { sql, params };
}

export { ADSB, AIS, TLE, EW, DARK_VESSEL, EVENT, NOTAM };

/**
 * Insert a homogeneous batch with one query; on failure, fall back to per-row inserts so a
 * single poison row (e.g. an FK or NOT NULL violation) can't drop the whole batch.
 */
async function insertSpec(pool: Pool, spec: DomainSpec, envelopes: Envelope[]): Promise<number> {
  if (envelopes.length === 0) return 0;
  try {
    const { sql, params } = buildBatchInsert(spec, envelopes);
    return (await pool.query(sql, params)).rowCount ?? 0;
  } catch {
    let written = 0;
    for (const env of envelopes) {
      try {
        const { sql, params } = buildBatchInsert(spec, [env]);
        written += (await pool.query(sql, params)).rowCount ?? 0;
      } catch {
        // Skip the offending row; the rest of the batch still lands.
      }
    }
    return written;
  }
}

/** Route a domain batch to its table(s) and execute, returning the number of rows written. */
async function writeBatchInner(pool: Pool, domain: string, envelopes: Envelope[]): Promise<number> {
  const simple = SIMPLE_SPECS[domain];
  if (simple) return insertSpec(pool, simple, envelopes);

  if (domain === "context") {
    const groups: ReadonlyArray<readonly [DomainSpec, Envelope[]]> = [
      [DARK_VESSEL, envelopes.filter((e) => p(e).kind === "dark_vessel")],
      [EVENT, envelopes.filter((e) => p(e).kind === "event")],
      [NOTAM, envelopes.filter((e) => p(e).kind === "notam")],
    ];
    let written = 0;
    for (const [spec, batch] of groups) written += await insertSpec(pool, spec, batch);
    return written;
  }

  return 0; // unknown domain: drop (the schema registry is the upstream guard)
}

/**
 * Route a domain batch to its table(s) and execute. Increments
 * worldview_history_rows_written_total{domain} by the number of rows actually inserted (the metric
 * is best-effort and never affects the write result).
 */
export async function writeBatch(pool: Pool, domain: string, envelopes: Envelope[]): Promise<number> {
  if (envelopes.length === 0) return 0;
  const written = await writeBatchInner(pool, domain, envelopes);
  if (written > 0) {
    try {
      historyRowsWrittenTotal.inc({ domain }, written);
    } catch {
      // metrics must never affect the write path
    }
  }
  return written;
}
