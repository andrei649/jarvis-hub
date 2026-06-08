import { createHmac, timingSafeEqual } from "node:crypto";

// AuthN primitive (ticket H19.4.2) — a tiny, dependency-free HS256 JWT sign/verify built on
// node:crypto. We deliberately avoid pulling in `jsonwebtoken` (no new dep): WorldView is local-first
// and only needs symmetric verification of an "OIDC-style" bearer. In a real deployment an external
// OIDC provider mints these tokens; `signToken` exists for tests/tooling (and a JARVIS minter), and
// `verifyToken` is what the request guard calls. Both are pure (no I/O); verify NEVER throws and uses
// a constant-time signature compare, rejecting expired (`exp`) / malformed tokens fail-CLOSED.

// The role lattice: viewer < analyst < admin. Carried in the token so RBAC can map role->permission.
export type Role = "viewer" | "analyst" | "admin";

export const ROLES: readonly Role[] = ["viewer", "analyst", "admin"];

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

// The verified claim set. `sub` identifies the principal; `role` drives RBAC; `aois` (when present)
// is the ABAC scope — the allowed AOI/region ids. Omitted or `["*"]` means "all AOIs" (no scoping).
// `exp`/`iat` are UNIX seconds (UTC), matching the rest of the API's time convention.
export interface Claims {
  sub: string;
  role: Role;
  aois?: string[];
  exp?: number;
  iat?: number;
  [key: string]: unknown;
}

// The fixed JOSE header for our single supported algorithm. We don't honor the token's own `alg`
// header for selecting the verifier (that would invite alg-confusion / "alg:none" attacks): we ALWAYS
// verify HS256 and additionally require the header to declare HS256.
const HEADER = { alg: "HS256", typ: "JWT" } as const;

// base64url encode/decode without padding, per RFC 7515.
function b64urlEncode(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(part: string): Buffer {
  // Restore standard base64 (+/) and pad to a multiple of 4 before decoding.
  const padded = part.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  return Buffer.from(padded + pad, "base64");
}

// HMAC-SHA256 over `<header>.<payload>` → the raw signature bytes.
function hmac(signingInput: string, secret: string): Buffer {
  return createHmac("sha256", secret).update(signingInput).digest();
}

/**
 * Mint an HS256 token for `claims`, signed with `secret`. `ttlS` (default 1h) sets `exp = now+ttlS`;
 * `iat` is stamped to now. Pass `now` (UNIX seconds) to make minting deterministic in tests. Intended
 * for tests/tooling and a JARVIS token minter — the production verifier accepts any HS256 token an
 * external OIDC provider signs with the same secret.
 */
export function signToken(
  claims: Claims,
  secret: string,
  ttlS = 3600,
  now: number = Math.floor(Date.now() / 1000),
): string {
  const body: Claims = { iat: now, exp: now + ttlS, ...claims };
  const headerPart = b64urlEncode(Buffer.from(JSON.stringify(HEADER), "utf8"));
  const payloadPart = b64urlEncode(Buffer.from(JSON.stringify(body), "utf8"));
  const signingInput = `${headerPart}.${payloadPart}`;
  const sig = b64urlEncode(hmac(signingInput, secret));
  return `${signingInput}.${sig}`;
}

// The discriminated verify result — never throws; the caller branches on `ok`.
export type VerifyResult = { ok: true; claims: Claims } | { ok: false; reason: string };

/**
 * Verify an HS256 bearer token against `secret`. Returns `{ ok, claims }` on success, otherwise
 * `{ ok:false, reason }`. Fail-CLOSED: any structural problem, a bad/short signature, a non-HS256
 * header, a missing/non-string `sub`, an invalid `role`, or an expired `exp` (compared against `now`,
 * UNIX seconds UTC, default = wall clock) all return `ok:false`. The signature compare is
 * constant-time and length-guarded.
 */
export function verifyToken(
  token: string,
  secret: string,
  now: number = Math.floor(Date.now() / 1000),
): VerifyResult {
  if (typeof token !== "string" || token.length === 0) {
    return { ok: false, reason: "missing token" };
  }
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed token" };
  const [headerPart, payloadPart, sigPart] = parts as [string, string, string];

  // Verify the signature FIRST (constant-time) so we never trust an unsigned payload.
  const expected = hmac(`${headerPart}.${payloadPart}`, secret);
  let provided: Buffer;
  try {
    provided = b64urlDecode(sigPart);
  } catch {
    return { ok: false, reason: "malformed signature" };
  }
  // Length-guard before timingSafeEqual (it throws on unequal lengths); unequal length = bad sig.
  if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
    return { ok: false, reason: "bad signature" };
  }

  // Signature is valid — now parse header + payload (guarded; malformed JSON = reject).
  let header: unknown;
  let payload: unknown;
  try {
    header = JSON.parse(b64urlDecode(headerPart).toString("utf8"));
    payload = JSON.parse(b64urlDecode(payloadPart).toString("utf8"));
  } catch {
    return { ok: false, reason: "malformed json" };
  }
  if (!header || typeof header !== "object" || (header as { alg?: unknown }).alg !== "HS256") {
    return { ok: false, reason: "unsupported alg" };
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, reason: "malformed payload" };
  }
  const claims = payload as Claims;

  if (typeof claims.sub !== "string" || claims.sub.length === 0) {
    return { ok: false, reason: "missing sub" };
  }
  if (!isRole(claims.role)) {
    return { ok: false, reason: "invalid role" };
  }
  // `aois`, when present, must be an array of strings (else we can't safely scope ABAC).
  if (claims.aois !== undefined) {
    if (!Array.isArray(claims.aois) || claims.aois.some((a) => typeof a !== "string")) {
      return { ok: false, reason: "invalid aois" };
    }
  }
  // Expiry is in UNIX seconds (UTC). A missing `exp` is allowed (long-lived service token); a present
  // one must be strictly in the future relative to `now`.
  if (claims.exp !== undefined) {
    if (typeof claims.exp !== "number" || !Number.isFinite(claims.exp)) {
      return { ok: false, reason: "invalid exp" };
    }
    if (now >= claims.exp) return { ok: false, reason: "expired" };
  }

  return { ok: true, claims };
}
