import type { Pool, PoolClient } from "pg";
import { MAX_FEATURES } from "../types.js";
import {
  computeEntryHash,
  verifyChain,
  type AuditChainRow,
  type StoredChainRow,
  type VerifyResult,
} from "../ontology/auditChain.js";

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
  prevHash: string | null;
  entryHash: string;
}

// Constant key for the transaction-scoped advisory lock that serializes chain appends (any stable
// application-chosen value; pg_advisory_xact_lock(bigint) takes a signed 64-bit key). See recordAction.
const CHAIN_LOCK_KEY = 0x4f_6e_74_6f_41_75_64; // "OntoAud" bytes — well within signed bigint range

/**
 * Append one audit row for an action invocation and return the persisted row (id + ts stamped by the
 * DB). The row is part of a TAMPER-EVIDENT HASH CHAIN (ticket H19.4.4): prev_hash = the previous
 * row's entry_hash (GENESIS at the head), entry_hash = sha256(prev_hash + canonicalize(row)) — see
 * ontology/auditChain.ts for the exact construction.
 *
 * CONCURRENCY. entry_hash depends on this row's id AND ts, which are DB-generated, so we can't
 * compute the hash before knowing them. We run inside a TRANSACTION and take a transaction-scoped
 * ADVISORY LOCK (pg_advisory_xact_lock) on a fixed key so only one writer appends to the chain tip at
 * a time — this is what keeps the chain valid under concurrent inserts (a plain `SELECT tip ... FOR
 * UPDATE` can't lock the as-yet-uninserted next row, leaving a gap; the advisory lock has no such
 * gap and auto-releases on commit/rollback). Holding the lock we: (1) read the tip's entry_hash as
 * prev_hash, (2) reserve this row's id from the sequence and stamp ts = now(), (3) compute entry_hash
 * in TS, (4) INSERT the row with explicit id/ts/prev_hash/entry_hash. The audit write is the
 * chain-of-custody guarantee, so a missing table (or any error) re-throws rather than silently
 * dropping the record.
 */
export async function recordAction(
  pool: Pool,
  entry: ActionAuditEntry,
): Promise<ActionAuditRow> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    // Serialize chain appends so prev_hash always points at the true tip (auto-released on commit).
    await client.query("SELECT pg_advisory_xact_lock($1)", [CHAIN_LOCK_KEY]);

    // Reserve this row's id + ts and read the current chain tip, all under the lock. id/ts are
    // generated here (not by column DEFAULT) because the hash must be computed from the exact values
    // that get stored. ts is reserved as WHOLE UNIX SECONDS (floor(epoch)::bigint): the row stores
    // to_timestamp(ts) and verify re-derives extract(epoch FROM ts) — an integral seconds value
    // round-trips byte-identically through a microsecond timestamptz, whereas a fractional epoch
    // double would not, causing a false `entry_hash mismatch` on a real-DB verify (ticket H19.4.4).
    // NOTE: this integral coercion is for the SCALAR audit ts ONLY — do NOT apply ::bigint rounding
    // to any composite entity id elsewhere.
    const head = await client.query(
      `SELECT nextval('ontology_actions_id_seq')::bigint            AS id,
              floor(extract(epoch FROM now()))::bigint              AS ts,
              (SELECT entry_hash FROM ontology_actions
                 ORDER BY id DESC LIMIT 1)                          AS tip_hash`,
    );
    const headRow = head.rows[0] as Record<string, unknown>;
    const id = Number(headRow.id);
    const ts = Number(headRow.ts);
    const prevHash = headRow.tip_hash == null ? null : String(headRow.tip_hash);

    const params = entry.params ?? {};
    const result = entry.result === undefined ? null : entry.result;
    const source = entry.source ?? "api";
    const actor = entry.actor ?? null;

    const chainRow: AuditChainRow = {
      id,
      ts,
      actor,
      objectType: entry.objectType,
      objectId: entry.objectId,
      action: entry.action,
      params,
      result,
      source,
    };
    const entryHash = computeEntryHash(prevHash, chainRow);

    const sql = `
      INSERT INTO ontology_actions
        (id, ts, actor, object_type, object_id, action, params, result, source, prev_hash, entry_hash)
      VALUES ($1, to_timestamp($2), $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11)
      RETURNING id, extract(epoch FROM ts) AS ts, actor,
                object_type, object_id, action, params, result, source, prev_hash, entry_hash`;
    const res = await client.query(sql, [
      id,
      ts,
      actor,
      entry.objectType,
      entry.objectId,
      entry.action,
      JSON.stringify(params),
      result === null ? null : JSON.stringify(result),
      source,
      prevHash,
      entryHash,
    ]);
    await client.query("COMMIT");
    return toAuditRow(res.rows[0] as Record<string, unknown>);
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // ignore rollback failure; surface the original error
    }
    throw err;
  } finally {
    client.release();
  }
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
           object_type, object_id, action, params, result, source, prev_hash, entry_hash
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
 * Fetch the hash chain in id (append) order — the input verifyChain() needs. Distinct from
 * listActions (newest-first, for display): chain verification MUST walk oldest→newest by id so each
 * row's prev_hash can be matched to the prior row's entry_hash. Degrades to [] on undefined_table so
 * /audit/verify on an un-applied schema reports an (vacuously valid) empty chain rather than 500.
 */
export async function fetchChain(
  pool: Pool,
  { limit }: { limit?: number } = {},
): Promise<StoredChainRow[]> {
  const cap = Math.min(limit && limit > 0 ? Math.floor(limit) : MAX_FEATURES, MAX_FEATURES);
  const sql = `
    SELECT id, extract(epoch FROM ts) AS ts, actor,
           object_type, object_id, action, params, result, source, prev_hash, entry_hash
    FROM ontology_actions
    ORDER BY id ASC
    LIMIT ${cap}`;
  try {
    const res = await pool.query(sql);
    return res.rows.map((r) => toStoredChainRow(r as Record<string, unknown>));
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return [];
  }
}

// Page size for the COMPLETE verification walk. fetchChain (the display reader) caps at MAX_FEATURES;
// verification must instead page the WHOLE chain so it can't return a false all-clear past one page.
const VERIFY_PAGE_SIZE = MAX_FEATURES;

/**
 * Fetch the ENTIRE chain in id ASC order, paging by `id > lastId` until exhausted. Unlike fetchChain
 * (capped at MAX_FEATURES for display), this never stops early: verification of a >page-sized chain
 * MUST walk every row, or tampering past the cap would slip through as a false ok=true (ticket
 * H19.4.4 / review HIGH). Degrades to [] on undefined_table so a verify against an un-applied schema
 * reports a vacuously-valid empty chain rather than 500.
 */
async function fetchEntireChain(pool: Pool): Promise<StoredChainRow[]> {
  const all: StoredChainRow[] = [];
  let lastId = -Infinity; // first page starts above the smallest possible id
  try {
    for (;;) {
      // `id > $1` keyset-pages forward by the PK (monotonic append order); $1 is -1 on the first page
      // (ids are positive), then the last id seen, so each page strictly advances until none remain.
      const sql = `
        SELECT id, extract(epoch FROM ts) AS ts, actor,
               object_type, object_id, action, params, result, source, prev_hash, entry_hash
        FROM ontology_actions
        WHERE id > $1
        ORDER BY id ASC
        LIMIT ${VERIFY_PAGE_SIZE}`;
      const res = await pool.query(sql, [Number.isFinite(lastId) ? lastId : -1]);
      if (res.rows.length === 0) break;
      for (const r of res.rows) all.push(toStoredChainRow(r as Record<string, unknown>));
      lastId = all[all.length - 1]!.id;
      if (res.rows.length < VERIFY_PAGE_SIZE) break; // short page = last page
    }
  } catch (err) {
    if ((err as { code?: string }).code !== UNDEFINED_TABLE) throw err;
    return [];
  }
  return all;
}

/**
 * Fetch the chain and verify it — convenience wrapper used by GET /ontology/audit/verify. Pages the
 * ENTIRE chain (not just the first MAX_FEATURES rows) so verification is COMPLETE regardless of size:
 * a chain longer than one page is fully walked, and tampering in a later page is detected rather than
 * silently passing. Returns verifyChain's { ok, count, brokenAtId?, reason? } pinpointing the first
 * broken link (if any).
 */
export async function verifyAuditChain(pool: Pool): Promise<VerifyResult> {
  const rows = await fetchEntireChain(pool);
  return verifyChain(rows);
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
    prevHash: r.prev_hash == null ? null : String(r.prev_hash),
    entryHash: String(r.entry_hash),
  };
}

// Map a DB row to the StoredChainRow shape verifyChain consumes (camelCase + numeric ts + hashes).
function toStoredChainRow(r: Record<string, unknown>): StoredChainRow {
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
    prevHash: r.prev_hash == null ? null : String(r.prev_hash),
    entryHash: String(r.entry_hash),
  };
}
