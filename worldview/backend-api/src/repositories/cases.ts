import type { Pool } from "pg";
import { recordAction } from "./ontologyAudit.js";
import { MAX_FEATURES } from "../types.js";

// Collaborative CASE repository (ticket H19.4.5). Parameterized CRUD over the case file tables
// (cases / case_members / case_items / case_comments — see db/schema/12_cases.sql). Two analysts work
// a shared case: members, items and comments. Every MUTATING op ALSO appends a row to the existing
// tamper-evident ontology_actions HASH CHAIN via recordAction (objectType 'Case', objectId = the case
// id) so the case history is auditable and tamper-evident — we reuse the audit, we don't reinvent it.
//
// Reads degrade to []/null on a missing table (Postgres 42P01) the way ontology.ts/history.ts do, so
// the API still answers on a partially-applied schema. Times are UNIX seconds on read (extract(epoch
// ...)); the tables default the timestamps on write. All SQL is parameterized.

// Postgres "undefined_table" — a backing case table isn't applied. Reads degrade gracefully; mutating
// ops re-throw (a write against an absent table MUST surface).
const UNDEFINED_TABLE = "42P01";

const DEFAULT_LIMIT = 200;

// The audited Case object type + action names (mirrors ontology actions; reused in the hash chain).
const CASE_OBJECT_TYPE = "Case";

export type CaseStatus = "open" | "closed" | "archived";
export type CaseMemberRole = "owner" | "collaborator" | "viewer";

export interface CaseRow {
  id: number;
  title: string;
  description: string | null;
  status: CaseStatus;
  createdBy: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface CaseMemberRow {
  caseId: number;
  actor: string;
  role: CaseMemberRole;
  addedAt: number;
}

export interface CaseItemRow {
  id: number;
  caseId: number;
  objectType: string;
  objectId: string;
  note: string | null;
  addedBy: string | null;
  addedAt: number;
}

export interface CaseCommentRow {
  id: number;
  caseId: number;
  actor: string | null;
  body: string;
  createdAt: number;
}

function clampLimit(limit: number | undefined): number {
  const n = limit && limit > 0 ? Math.floor(limit) : DEFAULT_LIMIT;
  return Math.min(n, MAX_FEATURES);
}

// Read path: run the query, degrade to [] on undefined_table (mirrors ontology.ts/history.ts).
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
    return [];
  }
}

// ---------------------------------------------------------------------------
// CASES
// ---------------------------------------------------------------------------

/**
 * Create a case and append a `case.create` audit row. The opening actor becomes both `created_by` AND
 * an `owner` member (in one round-trip each), so the creator is immediately on the collaboration roster.
 */
export async function createCase(
  pool: Pool,
  {
    title,
    description,
    actor,
  }: { title: string; description?: string | null; actor: string | null },
): Promise<CaseRow> {
  const sql = `
    INSERT INTO cases (title, description, created_by)
    VALUES ($1, $2, $3)
    RETURNING id, title, description, status,
              created_by,
              extract(epoch FROM created_at) AS created_at,
              extract(epoch FROM updated_at) AS updated_at`;
  const res = await pool.query(sql, [title, description ?? null, actor ?? null]);
  const row = toCaseRow(res.rows[0] as Record<string, unknown>);

  // The creator is the owner member (idempotent; no audit row for this implicit add).
  if (actor) {
    await pool.query(
      `INSERT INTO case_members (case_id, actor, role)
       VALUES ($1, $2, 'owner')
       ON CONFLICT (case_id, actor) DO UPDATE SET role = EXCLUDED.role`,
      [row.id, actor],
    );
  }

  await recordAction(pool, {
    actor,
    objectType: CASE_OBJECT_TYPE,
    objectId: String(row.id),
    action: "case.create",
    params: { title, description: description ?? null },
  });
  return row;
}

/** One case by id, or null when absent / table missing. */
export async function getCase(pool: Pool, id: number): Promise<CaseRow | null> {
  const sql = `
    SELECT id, title, description, status, created_by,
           extract(epoch FROM created_at) AS created_at,
           extract(epoch FROM updated_at) AS updated_at
    FROM cases
    WHERE id = $1`;
  const rows = await runOrEmpty(pool, sql, [id]);
  const row = rows[0];
  return row ? toCaseRow(row) : null;
}

/** List cases, newest first, capped at `limit`. Degrades to [] on a missing table. */
export async function listCases(
  pool: Pool,
  { limit }: { limit?: number } = {},
): Promise<CaseRow[]> {
  const sql = `
    SELECT id, title, description, status, created_by,
           extract(epoch FROM created_at) AS created_at,
           extract(epoch FROM updated_at) AS updated_at
    FROM cases
    ORDER BY created_at DESC, id DESC
    LIMIT ${clampLimit(limit)}`;
  const rows = await runOrEmpty(pool, sql, []);
  return rows.map(toCaseRow);
}

/**
 * Update a case's status (open/closed/archived), bump updated_at, and append a `case.<status>` audit
 * row (e.g. `case.close`). Returns the updated case, or null if it doesn't exist.
 */
export async function updateCaseStatus(
  pool: Pool,
  {
    id,
    status,
    actor,
  }: { id: number; status: CaseStatus; actor: string | null },
): Promise<CaseRow | null> {
  const sql = `
    UPDATE cases
    SET status = $2, updated_at = now()
    WHERE id = $1
    RETURNING id, title, description, status, created_by,
              extract(epoch FROM created_at) AS created_at,
              extract(epoch FROM updated_at) AS updated_at`;
  const res = await pool.query(sql, [id, status]);
  const row = res.rows[0];
  if (!row) return null;
  // Action name: case.close / case.archive / case.open (re-open), mapped from the new status.
  const action =
    status === "closed" ? "case.close" : status === "archived" ? "case.archive" : "case.open";
  await recordAction(pool, {
    actor,
    objectType: CASE_OBJECT_TYPE,
    objectId: String(id),
    action,
    params: { status },
  });
  return toCaseRow(row as Record<string, unknown>);
}

// ---------------------------------------------------------------------------
// MEMBERS
// ---------------------------------------------------------------------------

/**
 * Add (or re-role) a member on a case and append a `case.add_member` audit row. Idempotent on
 * (case_id, actor) — re-adding updates the role. Returns the persisted member row.
 */
export async function addMember(
  pool: Pool,
  {
    caseId,
    member,
    role,
    actor,
  }: { caseId: number; member: string; role?: CaseMemberRole; actor: string | null },
): Promise<CaseMemberRow> {
  const r = role ?? "collaborator";
  const sql = `
    INSERT INTO case_members (case_id, actor, role)
    VALUES ($1, $2, $3)
    ON CONFLICT (case_id, actor) DO UPDATE SET role = EXCLUDED.role
    RETURNING case_id, actor, role, extract(epoch FROM added_at) AS added_at`;
  const res = await pool.query(sql, [caseId, member, r]);
  await recordAction(pool, {
    actor,
    objectType: CASE_OBJECT_TYPE,
    objectId: String(caseId),
    action: "case.add_member",
    params: { member, role: r },
  });
  return toMemberRow(res.rows[0] as Record<string, unknown>);
}

/** List a case's members, earliest joined first. Degrades to [] on a missing table. */
export async function listMembers(pool: Pool, caseId: number): Promise<CaseMemberRow[]> {
  const sql = `
    SELECT case_id, actor, role, extract(epoch FROM added_at) AS added_at
    FROM case_members
    WHERE case_id = $1
    ORDER BY added_at ASC, actor ASC`;
  const rows = await runOrEmpty(pool, sql, [caseId]);
  return rows.map(toMemberRow);
}

/**
 * Remove a member from a case and append a `case.remove_member` audit row. Returns true if a row was
 * removed (false when the member wasn't on the case).
 */
export async function removeMember(
  pool: Pool,
  { caseId, member, actor }: { caseId: number; member: string; actor: string | null },
): Promise<boolean> {
  const res = await pool.query(
    `DELETE FROM case_members WHERE case_id = $1 AND actor = $2`,
    [caseId, member],
  );
  const removed = (res.rowCount ?? 0) > 0;
  if (removed) {
    await recordAction(pool, {
      actor,
      objectType: CASE_OBJECT_TYPE,
      objectId: String(caseId),
      action: "case.remove_member",
      params: { member },
    });
  }
  return removed;
}

// ---------------------------------------------------------------------------
// ITEMS
// ---------------------------------------------------------------------------

/**
 * Pin an ontology object/event into a case and append a `case.add_item` audit row. Returns the
 * persisted item row.
 */
export async function addItem(
  pool: Pool,
  {
    caseId,
    objectType,
    objectId,
    note,
    actor,
  }: {
    caseId: number;
    objectType: string;
    objectId: string;
    note?: string | null;
    actor: string | null;
  },
): Promise<CaseItemRow> {
  const sql = `
    INSERT INTO case_items (case_id, object_type, object_id, note, added_by)
    VALUES ($1, $2, $3, $4, $5)
    RETURNING id, case_id, object_type, object_id, note, added_by,
              extract(epoch FROM added_at) AS added_at`;
  const res = await pool.query(sql, [
    caseId,
    objectType,
    objectId,
    note ?? null,
    actor ?? null,
  ]);
  await recordAction(pool, {
    actor,
    objectType: CASE_OBJECT_TYPE,
    objectId: String(caseId),
    action: "case.add_item",
    params: { objectType, objectId, note: note ?? null },
  });
  return toItemRow(res.rows[0] as Record<string, unknown>);
}

/** List a case's items, newest first. Degrades to [] on a missing table. */
export async function listItems(pool: Pool, caseId: number): Promise<CaseItemRow[]> {
  const sql = `
    SELECT id, case_id, object_type, object_id, note, added_by,
           extract(epoch FROM added_at) AS added_at
    FROM case_items
    WHERE case_id = $1
    ORDER BY added_at DESC, id DESC`;
  const rows = await runOrEmpty(pool, sql, [caseId]);
  return rows.map(toItemRow);
}

// ---------------------------------------------------------------------------
// COMMENTS
// ---------------------------------------------------------------------------

/**
 * Add a comment to a case and append a `case.comment` audit row. Returns the persisted comment row.
 */
export async function addComment(
  pool: Pool,
  {
    caseId,
    body,
    actor,
  }: { caseId: number; body: string; actor: string | null },
): Promise<CaseCommentRow> {
  const sql = `
    INSERT INTO case_comments (case_id, actor, body)
    VALUES ($1, $2, $3)
    RETURNING id, case_id, actor, body, extract(epoch FROM created_at) AS created_at`;
  const res = await pool.query(sql, [caseId, actor ?? null, body]);
  await recordAction(pool, {
    actor,
    objectType: CASE_OBJECT_TYPE,
    objectId: String(caseId),
    action: "case.comment",
    params: { body },
  });
  return toCommentRow(res.rows[0] as Record<string, unknown>);
}

/** List a case's comments, oldest first (thread order). Degrades to [] on a missing table. */
export async function listComments(pool: Pool, caseId: number): Promise<CaseCommentRow[]> {
  const sql = `
    SELECT id, case_id, actor, body, extract(epoch FROM created_at) AS created_at
    FROM case_comments
    WHERE case_id = $1
    ORDER BY created_at ASC, id ASC`;
  const rows = await runOrEmpty(pool, sql, [caseId]);
  return rows.map(toCommentRow);
}

// ---------------------------------------------------------------------------
// Row mappers (snake_case DB rows -> camelCase, numeric ts as UNIX seconds).
// ---------------------------------------------------------------------------

function toCaseRow(r: Record<string, unknown>): CaseRow {
  return {
    id: Number(r.id),
    title: String(r.title),
    description: r.description == null ? null : String(r.description),
    status: String(r.status) as CaseStatus,
    createdBy: r.created_by == null ? null : String(r.created_by),
    createdAt: Number(r.created_at),
    updatedAt: Number(r.updated_at),
  };
}

function toMemberRow(r: Record<string, unknown>): CaseMemberRow {
  return {
    caseId: Number(r.case_id),
    actor: String(r.actor),
    role: String(r.role) as CaseMemberRole,
    addedAt: Number(r.added_at),
  };
}

function toItemRow(r: Record<string, unknown>): CaseItemRow {
  return {
    id: Number(r.id),
    caseId: Number(r.case_id),
    objectType: String(r.object_type),
    objectId: String(r.object_id),
    note: r.note == null ? null : String(r.note),
    addedBy: r.added_by == null ? null : String(r.added_by),
    addedAt: Number(r.added_at),
  };
}

function toCommentRow(r: Record<string, unknown>): CaseCommentRow {
  return {
    id: Number(r.id),
    caseId: Number(r.case_id),
    actor: r.actor == null ? null : String(r.actor),
    body: String(r.body),
    createdAt: Number(r.created_at),
  };
}
