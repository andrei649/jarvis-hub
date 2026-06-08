import type { Pool } from "pg";
import { emptyCollection, rowsToFeatureCollection } from "../geojson.js";
import {
  LIVENESS_SECONDS,
  MAX_FEATURES,
  type BBox,
  type FeatureCollection,
  type Lod,
} from "../types.js";

// Minute-LOD reads from continuous aggregates (design doc §8.3); buckets are coarse, so use a
// wider window to ensure at least one bucket is captured at T.
const MINUTE_WINDOW_SECONDS = 600;

// Historical "as-of T" reconstruction (design doc §8.2). Each layer returns the last-known
// state at or before T for every entity, viewport-bounded, as a GeoJSON FeatureCollection.

function bboxClause(bbox: BBox | null, firstParam: number, col = "geom"): {
  clause: string;
  params: number[];
} {
  if (!bbox) return { clause: "", params: [] };
  const p = firstParam;
  return {
    clause: ` AND ${col} && ST_MakeEnvelope($${p}, $${p + 1}, $${p + 2}, $${p + 3}, 4326)`,
    params: [bbox.w, bbox.s, bbox.e, bbox.n],
  };
}

// Postgres "undefined_table" — the continuous aggregate isn't materialized (or we're on plain
// Postgres). The minute-LOD path falls back to the raw query so the API degrades gracefully.
const UNDEFINED_TABLE = "42P01";

async function queryWithRawFallback(
  pool: Pool,
  primarySql: string,
  fallbackSql: string,
  params: unknown[],
): Promise<FeatureCollection> {
  try {
    const res = await pool.query(primarySql, params);
    return rowsToFeatureCollection(res.rows);
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    const res = await pool.query(fallbackSql, params);
    return rowsToFeatureCollection(res.rows);
  }
}

export async function flightsAsOf(
  pool: Pool,
  t: number,
  bbox: BBox | null,
  lod: Lod = "raw",
): Promise<FeatureCollection> {
  const bc = bboxClause(bbox, 2);
  const params = [t, ...bc.params];
  const rawSql = `
    SELECT DISTINCT ON (icao24)
      icao24, extract(epoch FROM ts) AS ts, alt_m, gs_kt, track_deg,
      callsign, squawk, on_ground, is_military,
      source, extract(epoch FROM ingested_at) AS ingested_at,
      ST_AsGeoJSON(geom) AS geojson
    FROM adsb_positions
    WHERE ts <= to_timestamp($1)
      AND ts >  to_timestamp($1) - make_interval(secs => ${LIVENESS_SECONDS.adsb})${bc.clause}
    ORDER BY icao24, ts DESC
    LIMIT ${MAX_FEATURES}`;
  if (lod === "minute") {
    const minuteSql = `
    SELECT DISTINCT ON (icao24)
      icao24, extract(epoch FROM bucket) AS ts, alt_m, gs_kt, track_deg, is_military,
      ST_AsGeoJSON(geom) AS geojson
    FROM adsb_positions_1m
    WHERE bucket <= to_timestamp($1)
      AND bucket >  to_timestamp($1) - make_interval(secs => ${MINUTE_WINDOW_SECONDS})${bc.clause}
    ORDER BY icao24, bucket DESC
    LIMIT ${MAX_FEATURES}`;
    return queryWithRawFallback(pool, minuteSql, rawSql, params);
  }
  const res = await pool.query(rawSql, params);
  return rowsToFeatureCollection(res.rows);
}

export async function vesselsAsOf(
  pool: Pool,
  t: number,
  bbox: BBox | null,
  lod: Lod = "raw",
): Promise<FeatureCollection> {
  const bc = bboxClause(bbox, 2);
  const params = [t, ...bc.params];
  const rawSql = `
    SELECT DISTINCT ON (mmsi)
      mmsi, extract(epoch FROM ts) AS ts, sog_kt, cog_deg, heading_deg, nav_status,
      source, extract(epoch FROM ingested_at) AS ingested_at,
      ST_AsGeoJSON(geom) AS geojson
    FROM ais_positions
    WHERE ts <= to_timestamp($1)
      AND ts >  to_timestamp($1) - make_interval(secs => ${LIVENESS_SECONDS.ais})${bc.clause}
    ORDER BY mmsi, ts DESC
    LIMIT ${MAX_FEATURES}`;
  if (lod === "minute") {
    const minuteSql = `
    SELECT DISTINCT ON (mmsi)
      mmsi, extract(epoch FROM bucket) AS ts, sog_kt, cog_deg, ST_AsGeoJSON(geom) AS geojson
    FROM ais_positions_1m
    WHERE bucket <= to_timestamp($1)
      AND bucket >  to_timestamp($1) - make_interval(secs => ${MINUTE_WINDOW_SECONDS})${bc.clause}
    ORDER BY mmsi, bucket DESC
    LIMIT ${MAX_FEATURES}`;
    return queryWithRawFallback(pool, minuteSql, rawSql, params);
  }
  const res = await pool.query(rawSql, params);
  return rowsToFeatureCollection(res.rows);
}

export async function satellitesAsOf(
  pool: Pool,
  t: number,
  bbox: BBox | null,
  _lod: Lod = "raw",
): Promise<FeatureCollection> {
  // A satellite is "in view" if its sub-satellite point OR its FOOTPRINT intersects the viewport —
  // a satellite overhead just outside the box can still illuminate it. Match on either geometry
  // (both GiST-indexed: geom_gist + footprint_gist). Built inline (not bboxClause) so we can OR two
  // columns against the same envelope; the four envelope params follow $1 (t) as $2..$5.
  let bboxFilter = "";
  const bboxParams: number[] = [];
  if (bbox) {
    const env = `ST_MakeEnvelope($2, $3, $4, $5, 4326)`;
    bboxFilter = ` AND (geom && ${env} OR footprint && ${env})`;
    bboxParams.push(bbox.w, bbox.s, bbox.e, bbox.n);
  }
  const sql = `
    SELECT DISTINCT ON (norad_id)
      norad_id, extract(epoch FROM ts) AS ts, sensor_type, velocity_kms, is_sunlit,
      source, extract(epoch FROM ingested_at) AS ingested_at,
      ST_AsGeoJSON(geom) AS geojson, ST_AsGeoJSON(footprint) AS footprint
    FROM satellite_ephemeris
    WHERE ts <= to_timestamp($1)
      AND ts >  to_timestamp($1) - make_interval(secs => ${LIVENESS_SECONDS.tle})${bboxFilter}
    ORDER BY norad_id, ts DESC
    LIMIT ${MAX_FEATURES}`;
  const res = await pool.query(sql, [t, ...bboxParams]);
  return rowsToFeatureCollection(res.rows, "geojson", ["footprint"]);
}

export async function jammingAsOf(
  pool: Pool,
  t: number,
  bbox: BBox | null,
  _lod: Lod = "raw",
): Promise<FeatureCollection> {
  const bc = bboxClause(bbox, 2, "h3_geom");
  const sql = `
    SELECT DISTINCT ON (h3_index)
      h3_index, extract(epoch FROM ts) AS ts, intensity, sample_count, h3_resolution,
      source, extract(epoch FROM ingested_at) AS ingested_at,
      ST_AsGeoJSON(h3_geom) AS geojson
    FROM gps_jamming
    WHERE ts <= to_timestamp($1)
      AND ts >  to_timestamp($1) - make_interval(secs => ${LIVENESS_SECONDS.ew})${bc.clause}
    ORDER BY h3_index, ts DESC
    LIMIT ${MAX_FEATURES}`;
  const res = await pool.query(sql, [t, ...bc.params]);
  return rowsToFeatureCollection(res.rows);
}

/** Contextual intel: NOTAMs + strike zones active at T, recent events, and active dark vessels. */
export async function contextAsOf(
  pool: Pool,
  t: number,
  bbox: BBox | null,
  _lod: Lod = "raw",
): Promise<FeatureCollection> {
  const notamBox = bboxClause(bbox, 2);
  const notams = await pool.query(
    `SELECT 'notam' AS kind, id, notam_type,
            extract(epoch FROM effective_from) AS effective_from,
            extract(epoch FROM effective_to) AS effective_to,
            ST_AsGeoJSON(geom) AS geojson
       FROM notams
      WHERE effective_from <= to_timestamp($1)
        AND (effective_to IS NULL OR effective_to >= to_timestamp($1))${notamBox.clause}`,
    [t, ...notamBox.params],
  );

  const zoneBox = bboxClause(bbox, 2);
  const zones = await pool.query(
    `SELECT 'strike_zone' AS kind, id, name, severity,
            extract(epoch FROM effective_from) AS effective_from,
            extract(epoch FROM effective_to) AS effective_to,
            ST_AsGeoJSON(geom) AS geojson
       FROM strike_zones
      WHERE effective_from <= to_timestamp($1)
        AND (effective_to IS NULL OR effective_to >= to_timestamp($1))${zoneBox.clause}`,
    [t, ...zoneBox.params],
  );

  // Recent events within a 1-hour trailing window of T.
  const eventBox = bboxClause(bbox, 2);
  const events = await pool.query(
    `SELECT 'event' AS kind, event_id, category, severity,
            extract(epoch FROM ts) AS ts, ST_AsGeoJSON(geom) AS geojson
       FROM geopolitical_events
      WHERE ts <= to_timestamp($1)
        AND ts >  to_timestamp($1) - make_interval(secs => 3600)${eventBox.clause}`,
    [t, ...eventBox.params],
  );

  // Latest dark-vessel state per MMSI, still flagged dark at T. Viewport-bounded on the displayed
  // geometry (COALESCE(extrapolated_geom, last_seen_geom)) and LIMITed like every sibling arm —
  // without these this DISTINCT ON (mmsi) scan is unbounded, and contextAsOf is called up to
  // MAX_FRAMES times per export (review MEDIUM).
  const darkBox = bboxClause(bbox, 2, "COALESCE(extrapolated_geom, last_seen_geom)");
  const dark = await pool.query(
    `SELECT DISTINCT ON (mmsi) 'dark_vessel' AS kind, mmsi, geofence_id, gap_seconds,
            extract(epoch FROM ts) AS ts, status,
            ST_AsGeoJSON(COALESCE(extrapolated_geom, last_seen_geom)) AS geojson
       FROM dark_vessel_events
      WHERE ts <= to_timestamp($1) AND status = 'dark'${darkBox.clause}
      ORDER BY mmsi, ts DESC
      LIMIT ${MAX_FEATURES}`,
    [t, ...darkBox.params],
  );

  const fc = rowsToFeatureCollection([
    ...notams.rows,
    ...zones.rows,
    ...events.rows,
    ...dark.rows,
  ]);
  return fc;
}

export const HISTORY_BY_LAYER = {
  adsb: flightsAsOf,
  ais: vesselsAsOf,
  tle: satellitesAsOf,
  ew: jammingAsOf,
  context: contextAsOf,
} as const;

// Point-track layers (an entity has an ordered path over time): table + id column.
const TRACK_TABLES: Record<string, { table: string; id: string }> = {
  adsb: { table: "adsb_positions", id: "icao24" },
  ais: { table: "ais_positions", id: "mmsi" },
  tle: { table: "satellite_ephemeris", id: "norad_id" },
};

export const TRACK_LAYERS = Object.keys(TRACK_TABLES);

/**
 * One entity's trail over [from, to] as a GeoJSON LineString Feature (for a Deck.gl PathLayer).
 * `coordTimes` carries the per-vertex epochs for optional time-animation. Empty if < 2 points.
 */
export async function trackOf(
  pool: Pool,
  layer: string,
  entityId: string,
  from: number,
  to: number,
): Promise<FeatureCollection> {
  const spec = TRACK_TABLES[layer];
  if (!spec) return emptyCollection();
  const idValue = layer === "adsb" ? entityId : Number(entityId);
  const sql = `
    SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat, extract(epoch FROM ts) AS ts
    FROM ${spec.table}
    WHERE ${spec.id} = $1 AND ts >= to_timestamp($2) AND ts <= to_timestamp($3)
    ORDER BY ts ASC`;
  const res = await pool.query(sql, [idValue, from, to]);
  if (res.rows.length < 2) return emptyCollection();

  const coordinates = res.rows.map((r) => [Number(r.lon), Number(r.lat)]);
  const coordTimes = res.rows.map((r) => Number(r.ts));
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "LineString", coordinates },
        properties: {
          entity_id: String(entityId),
          layer,
          count: coordinates.length,
          ts_start: coordTimes[0],
          ts_end: coordTimes[coordTimes.length - 1],
          coordTimes,
        },
      },
    ],
  };
}
