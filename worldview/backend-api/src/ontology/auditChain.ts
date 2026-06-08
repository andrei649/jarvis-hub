import { createHash } from "node:crypto";

// Tamper-evident hash chain for the ontology action audit log (ticket H19.4.4). This module is the
// AUTHORITATIVE, pure, dependency-free definition of how an audit row is hashed and how the chain is
// verified — the repository (ontologyAudit.ts) computes entry_hash on insert using these functions,
// the verify endpoint replays a fetched chain through verifyChain(), and the unit tests pin the
// construction. Keeping the hashing here (not in SQL) means one place to reason about determinism.
//
// THE CHAIN. Rows are ordered by id (the bigserial PK = monotonic append order). Each row stores:
//   prev_hash  = the previous row's entry_hash (GENESIS for the first row)
//   entry_hash = sha256(prev_hash + '\n' + canonicalize(row))   [hex]
// Verification recomputes entry_hash for every row and ALSO checks prev_hash links to the prior
// row's entry_hash. Any mutation (a field changed), removal, insertion or reordering breaks at least
// one of those two checks, and we report the FIRST broken id.
//
// DETERMINISM IS THE WHOLE GAME. canonicalize() must produce byte-identical output for the row as
// written and the row as read back, on any machine, regardless of JS object key insertion order or
// jsonb round-tripping. So: fixed field order, recursively sorted object keys for the jsonb fields
// (params/result), numeric ts rendered with a stable representation, and explicit null markers.

/** Fixed sentinel for the genesis row's prev_hash (the first link has no predecessor). */
export const GENESIS = "GENESIS";

/** Sentinel for a SQL NULL field (actor/result). An unquoted bare token, so it can never collide
 *  with a JSON string "null" (which stableStringify emits WITH quotes). */
const NULL_MARKER = "\\null";

/** The audit-relevant fields of one row, in the shape the repository binds and the DB returns. */
export interface AuditChainRow {
  id: number;
  ts: number; // UNIX seconds (extract(epoch FROM ts)) — UTC instant, no timezone ambiguity
  actor: string | null;
  objectType: string;
  objectId: string;
  action: string;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  source: string;
}

/** A row as it comes off the chain, including the stored hashes (for verification). */
export interface StoredChainRow extends AuditChainRow {
  prevHash: string | null;
  entryHash: string;
}

/** Outcome of a chain verification. brokenAtId/reason are set iff ok === false. */
export interface VerifyResult {
  ok: boolean;
  count: number;
  brokenAtId?: number;
  reason?: string;
}

// Recursively produce a deterministic JSON string: object keys sorted, arrays kept in order, scalars
// JSON-encoded as-is. This is what makes a jsonb field hash identically no matter what key order the
// driver hands back. (We do NOT use JSON.stringify directly on the object — its output depends on
// insertion order.) undefined inside an object is dropped (matches JSON semantics); a top-level
// undefined/null becomes the literal "null".
export function stableStringify(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number") {
    // Non-finite numbers have no JSON form; pin them to "null" so canonicalization never throws.
    return Number.isFinite(value) ? JSON.stringify(value) : "null";
  }
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((v) => stableStringify(v)).join(",")}]`;
  }
  const obj = value as Record<string, unknown>;
  const keys = Object.keys(obj).sort();
  const parts: string[] = [];
  for (const k of keys) {
    if (obj[k] === undefined) continue; // JSON drops undefined-valued keys
    parts.push(`${JSON.stringify(k)}:${stableStringify(obj[k])}`);
  }
  return `{${parts.join(",")}}`;
}

/**
 * A deterministic, line-oriented serialization of the audit-relevant fields, in a FIXED order with
 * explicit per-field tags. The jsonb fields go through stableStringify (sorted keys) so object
 * key-order / round-trip differences can't change the hash. ts is rendered as an integer-or-float
 * UNIX-seconds literal (already a UTC instant). null actor/result use NULL_MARKER (an unquoted token),
 * distinct from an empty string, an empty object, or a literal "null" string field.
 */
export function canonicalize(row: AuditChainRow): string {
  return [
    `id:${row.id}`,
    `ts:${row.ts}`,
    `actor:${row.actor === null ? NULL_MARKER : stableStringify(row.actor)}`,
    `object_type:${stableStringify(row.objectType)}`,
    `object_id:${stableStringify(row.objectId)}`,
    `action:${stableStringify(row.action)}`,
    `params:${stableStringify(row.params ?? {})}`,
    `result:${row.result === null ? NULL_MARKER : stableStringify(row.result)}`,
    `source:${stableStringify(row.source)}`,
  ].join("\n");
}

/**
 * The chain hash for one row: sha256(prevHash + '\n' + canonicalize(row)) as lowercase hex. The
 * genesis row passes GENESIS as prevHash. prevHash may also be passed as null (treated as GENESIS)
 * so callers don't have to special-case the first insert.
 */
export function computeEntryHash(prevHash: string | null, row: AuditChainRow): string {
  const prev = prevHash === null ? GENESIS : prevHash;
  return createHash("sha256").update(`${prev}\n${canonicalize(row)}`).digest("hex");
}

/**
 * Walk rows in id order and verify the tamper-evident chain. For each row we check BOTH:
 *   1) link: prev_hash equals the previous row's entry_hash (GENESIS for the first row), and
 *   2) integrity: the recomputed entry_hash (from the stored prev_hash + the row's own fields)
 *      equals the stored entry_hash.
 * The first row that fails either check is reported via brokenAtId + a human reason; verification
 * stops there (the chain is meaningless past the first break). An empty log is vacuously ok.
 *
 * Note: rows are sorted defensively by id here, so a caller passing them out of order still yields a
 * correct (id-ordered) verification rather than a false "reordering" break.
 */
export function verifyChain(rows: StoredChainRow[]): VerifyResult {
  const ordered = [...rows].sort((a, b) => a.id - b.id);
  let prevEntryHash = GENESIS;
  for (let i = 0; i < ordered.length; i++) {
    const row = ordered[i]!;
    const expectedPrev = i === 0 ? null : prevEntryHash;
    // Link check: prev_hash must point at the prior row's entry_hash (genesis: GENESIS or null).
    const storedPrev = row.prevHash === null ? GENESIS : row.prevHash;
    const wantPrev = expectedPrev === null ? GENESIS : expectedPrev;
    if (storedPrev !== wantPrev) {
      return {
        ok: false,
        count: ordered.length,
        brokenAtId: row.id,
        reason:
          i === 0
            ? `genesis prev_hash mismatch: stored ${storedPrev}, expected ${wantPrev}`
            : `broken link: prev_hash ${storedPrev} does not match previous entry_hash ${wantPrev}`,
      };
    }
    // Integrity check: recompute the row's entry_hash from its stored prev_hash + fields.
    const recomputed = computeEntryHash(row.prevHash, row);
    if (recomputed !== row.entryHash) {
      return {
        ok: false,
        count: ordered.length,
        brokenAtId: row.id,
        reason: `entry_hash mismatch: row content does not match stored hash ${row.entryHash}`,
      };
    }
    prevEntryHash = row.entryHash;
  }
  return { ok: true, count: ordered.length };
}
