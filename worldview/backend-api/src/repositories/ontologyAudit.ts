import type { Pool } from "pg";
import { MAX_FEATURES } from "../types.js";

// Ontology action-audit repository (ticket H19.4.1). Every ontology ACTION (a write, e.g. annotate /
// watch) is appended to the `ontology_actions` audit table so "actions = audited endpoints" is
// verifiable: recordAction writes one immutable audit row per invocation, and listActions reads the
// trail back (optionally filtered by object). The `annotate` action additionally persists its note
// to `ontology_annotations` (handled in the route via recordAnnotation below). Times are UNIX
// seconds on read (extract(epoch ...)); the table defaults ts to now() on write. The audit table is
// a plain table (NOT a hypertable) created fresh in db/schema/11_ontology.sql.

// Postgres "undefined_table" — the audit table isn't applied yet. Reads degrade to []; writes
// re-throw (an unrecorded action MUST surface, since the audit guarantee is the point of the layer).
const UNDEFINED_TABLE = "42P01";

const DEFAULT_LIMIT = 200;

/** One audited action invocation. `result` is whatever the action returned (jsonb), null until set. */
export interface ActionAuditEntry {
  actor: string | null;
  objectType: string;
  objectId: string;
  action: string;
  params: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  source?: string;
}

/** A persisted audit row read back from the trail (ts is UNIX seconds). */
export interface ActionAuditRow {
  id: number;
  ts: number;
  actor: string | null;
  objectType: string;
  objectId: string;
  action: string;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  source: string;
}

/**
 * Append one audit row for an action invocation and return the persisted row (id + ts stamped by the
 * DB). Parameterized INSERT ... RETURNING; jsonb params bound as JSON.stringify'd text and cast in
 * SQL. The audit write is the chain-of-custody guarantee, so a missing table re-throws rather than
 * silently dropping the record.
 */
export async function recordAction(
  pool: Pool,
  entry: ActionAuditEntry,
): Promise<ActionAuditRow> {
  const sql = `
    INSERT INTO ontology_actions
      (actor, object_type, object_id, action, params, result, source)
    VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
    RETURNING id, extract(epoch FROM ts) AS ts, actor,
              object_type, object_id, action, params, result, source`;
  const params = [
    entry.actor ?? null,
    entry.objectType,
    entry.objectId,
    entry.action,
    JSON.stringify(entry.params ?? {}),
    entry.result === undefined ? null : JSON.stringify(entry.result),
    entry.source ?? "api",
  ];
  const res = await pool.query(sql, params);
  return toAuditRow(res.rows[0] as Record<string, unknown>);
}

/**
 * Read the audit trail, newest first, optionally filtered by object type and/or id. Degrades to []
 * if the audit table isn't applied yet (read path), mirroring the rest of the API.
 */
export async function listActions(
  pool: Pool,
  {
    objectType,
    objectId,
    limit,
  }: { objectType?: string; objectId?: string; limit?: number } = {},
): Promise<ActionAuditRow[]> {
  const filters: string[] = [];
  const params: unknown[] = [];
  if (objectType) {
    params.push(objectType);
    filters.push(`object_type = $${params.length}`);
  }
  if (objectId) {
    params.push(objectId);
    filters.push(`object_id = $${params.length}`);
  }
  const where = filters.length ? `\n    WHERE ${filters.join(" AND ")}` : "";
  const cap = Math.min(limit && limit > 0 ? Math.floor(limit) : DEFAULT_LIMIT, MAX_FEATURES);
  const sql = `
    SELECT id, extract(epoch FROM ts) AS ts, actor,
           object_type, object_id, action, params, result, source
    FROM ontology_actions${where}
    ORDER BY ts DESC, id DESC
    LIMIT ${cap}`;
  try {
    const res = await pool.query(sql, params);
    return res.rows.map((r) => toAuditRow(r as Record<string, unknown>));
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return [];
  }
}

/**
 * Persist an `annotate` note to ontology_annotations and return its id. Separate from the audit row
 * (which records THAT the action happened); this stores the note CONTENT so it can be read back later.
 */
export async function recordAnnotation(
  pool: Pool,
  {
    actor,
    objectType,
    objectId,
    note,
    tags,
  }: {
    actor: string | null;
    objectType: string;
    objectId: string;
    note: string;
    tags: string[];
  },
): Promise<{ annotationId: number }> {
  const sql = `
    INSERT INTO ontology_annotations (actor, object_type, object_id, note, tags)
    VALUES ($1, $2, $3, $4, $5::jsonb)
    RETURNING id`;
  const res = await pool.query(sql, [
    actor ?? null,
    objectType,
    objectId,
    note,
    JSON.stringify(tags ?? []),
  ]);
  return { annotationId: Number((res.rows[0] as Record<string, unknown>).id) };
}

// jsonb columns come back from `pg` already parsed into JS objects; coerce defensively in case a
// driver/path hands us a string (guard the implicit JSON.parse the way the rest of the code does).
function asJson(v: unknown): Record<string, unknown> | null {
  if (v == null) return null;
  if (typeof v === "string") {
    try {
      return JSON.parse(v) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  return v as Record<string, unknown>;
}

function toAuditRow(r: Record<string, unknown>): ActionAuditRow {
  return {
    id: Number(r.id),
    ts: Number(r.ts),
    actor: r.actor == null ? null : String(r.actor),
    objectType: String(r.object_type),
    objectId: String(r.object_id),
    action: String(r.action),
    params: asJson(r.params) ?? {},
    result: asJson(r.result),
    source: String(r.source),
  };
}
