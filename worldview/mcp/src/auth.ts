// Self-contained capability-token verification for the WorldView MCP boundary (ticket H19.3.2).
//
// The standalone MCP server cannot reuse JARVIS's in-process `CapabilityBroker`, so for the
// process boundary we verify a compact, HMAC-signed capability token. JARVIS — when it mints
// these — would do so via its CapabilityBroker (issuing the same signed shape); here we only
// *verify*. The token carries the scopes it authorises plus an expiry, so an MCP write tool can
// be gated on a single, offline, constant-time check with no shared in-memory state.
//
// Security posture (see ticket "known bug classes"):
//   - Fail CLOSED: a missing secret, malformed token, bad signature, expiry, or missing scope all
//     return `{ ok: false, reason }` — we never throw and never default to "allow".
//   - Constant-time signature compare via `crypto.timingSafeEqual`, guarding its equal-length
//     requirement (mismatched lengths => deny, without leaking via an exception).
//   - Audit lines go to STDERR only — stdout is the JSON-RPC channel (see server.ts).

import { createHmac, timingSafeEqual } from "node:crypto";

/** Claims carried by a verified capability token. `exp` is unix *seconds*. */
export interface CapabilityClaims {
  scopes: string[];
  exp: number;
  sub?: string;
}

/** Result of a verification attempt: a tagged union so callers branch on `ok` with no throws. */
export type VerifyResult =
  | { ok: true; claims: CapabilityClaims }
  | { ok: false; reason: string };

/** Options for `verifyCapability`; both injectable so tests are deterministic and self-contained. */
export interface VerifyOpts {
  /** HMAC secret shared with the token issuer (JARVIS's CapabilityBroker). Empty/undefined => deny. */
  secret: string | undefined;
  /** Current time as unix *seconds*; defaults to `Date.now()/1000`. Injected in tests. */
  now?: number;
}

/** Wildcard scope that grants every `worldview:*` capability (e.g. a broker-issued admin token). */
const WILDCARD_SCOPE = "worldview:*";

/** base64url-encode a UTF-8 string (no padding), matching the token's encoding on the issuer side. */
function b64urlEncode(input: string): string {
  return Buffer.from(input, "utf8").toString("base64url");
}

/** base64url-decode to a UTF-8 string; returns null on any malformed input (never throws). */
function b64urlDecode(input: string): string | null {
  try {
    return Buffer.from(input, "base64url").toString("utf8");
  } catch {
    return null;
  }
}

/** Compute the base64url(HMAC-SHA256(payload, secret)) signature for a payload segment. */
export function signPayload(payloadSegment: string, secret: string): string {
  return createHmac("sha256", secret).update(payloadSegment).digest("base64url");
}

/**
 * Mint a capability token: `base64url(JSON(claims)) + "." + base64url(HMAC-SHA256(payload))`.
 * Provided so tests (and any local tooling) can produce self-contained fixtures; in production
 * JARVIS's CapabilityBroker is the issuer and the MCP server only ever *verifies*.
 */
export function signCapability(claims: CapabilityClaims, secret: string): string {
  const payloadSegment = b64urlEncode(JSON.stringify(claims));
  const sigSegment = signPayload(payloadSegment, secret);
  return `${payloadSegment}.${sigSegment}`;
}

/** Constant-time equality for two base64url signature strings, safe against unequal lengths. */
function signaturesEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  // `timingSafeEqual` throws if the buffers differ in length; a length mismatch is already a
  // definitive "not equal", so short-circuit to deny rather than letting it throw.
  if (bufA.length !== bufB.length) return false;
  return timingSafeEqual(bufA, bufB);
}

/** True if `granted` authorises `required` (exact match or the `worldview:*` wildcard). */
function scopeSatisfies(granted: readonly string[], required: string): boolean {
  return granted.includes(required) || granted.includes(WILDCARD_SCOPE);
}

/**
 * Verify a capability token for one required scope. Returns `{ ok:true, claims }` only when the
 * signature is valid, the token is unexpired, and `requiredScope` is granted; otherwise
 * `{ ok:false, reason }`. NEVER throws — every malformed-input path maps to a `deny` reason.
 */
export function verifyCapability(
  token: string | undefined,
  requiredScope: string,
  opts: VerifyOpts,
): VerifyResult {
  // Fail closed when no secret is configured: without it we cannot trust any token.
  if (!opts.secret) return { ok: false, reason: "no-secret-configured" };
  if (typeof token !== "string" || token.trim() === "") {
    return { ok: false, reason: "missing-token" };
  }

  const parts = token.split(".");
  if (parts.length !== 2) return { ok: false, reason: "malformed-token" };
  const [payloadSegment, sigSegment] = parts as [string, string];
  if (payloadSegment === "" || sigSegment === "") {
    return { ok: false, reason: "malformed-token" };
  }

  // Recompute the expected signature and compare in constant time before trusting the payload.
  const expectedSig = signPayload(payloadSegment, opts.secret);
  if (!signaturesEqual(sigSegment, expectedSig)) {
    return { ok: false, reason: "bad-signature" };
  }

  const json = b64urlDecode(payloadSegment);
  if (json === null) return { ok: false, reason: "malformed-payload" };

  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return { ok: false, reason: "malformed-payload" };
  }
  if (typeof parsed !== "object" || parsed === null) {
    return { ok: false, reason: "malformed-payload" };
  }

  const candidate = parsed as Record<string, unknown>;
  const scopes = candidate.scopes;
  const exp = candidate.exp;
  if (!Array.isArray(scopes) || !scopes.every((s) => typeof s === "string")) {
    return { ok: false, reason: "malformed-claims" };
  }
  if (typeof exp !== "number" || !Number.isFinite(exp)) {
    return { ok: false, reason: "malformed-claims" };
  }

  const now = opts.now ?? Math.floor(Date.now() / 1000);
  if (exp <= now) return { ok: false, reason: "expired" };

  if (!scopeSatisfies(scopes as string[], requiredScope)) {
    return { ok: false, reason: "missing-scope" };
  }

  const sub = typeof candidate.sub === "string" ? candidate.sub : undefined;
  return { ok: true, claims: { scopes: scopes as string[], exp, sub } };
}

// --- Audit ------------------------------------------------------------------

/** One structured audit record for a capability decision on a write tool. */
export interface AuditEntry {
  tool: string;
  decision: "allow" | "deny";
  reason?: string;
  sub?: string;
}

/** A sink for audit lines. Defaults to stderr; injectable so tests can capture entries. */
export type AuditSink = (line: string) => void;

const defaultSink: AuditSink = (line) => {
  process.stderr.write(line);
};

/**
 * Write one structured audit line (JSON + newline) to the sink. Emits to STDERR by default —
 * NEVER stdout, which is the JSON-RPC stream. Returns the serialized record so callers/tests can
 * assert on it without re-parsing the sink.
 */
export function audit(entry: AuditEntry, sink: AuditSink = defaultSink): string {
  const record = {
    ts: new Date().toISOString(),
    tool: entry.tool,
    decision: entry.decision,
    ...(entry.reason !== undefined ? { reason: entry.reason } : {}),
    ...(entry.sub !== undefined ? { sub: entry.sub } : {}),
  };
  const line = JSON.stringify(record) + "\n";
  sink(line);
  return line;
}
