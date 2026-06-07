// Unit tests for the capability-token verifier and audit hook (`src/auth.ts`, ticket H19.3.2).
//
// Self-contained: token fixtures are minted in-test by signing with `node:crypto` and the test
// secret (via the exported `signCapability`), so there are no external fixtures. We assert the
// fail-CLOSED posture: a missing secret, malformed token, bad signature, expiry, or missing scope
// all DENY without throwing, and only a valid+unexpired+scoped token is allowed.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  audit,
  signCapability,
  signPayload,
  verifyCapability,
  type AuditEntry,
  type CapabilityClaims,
} from "../src/auth.js";

const SECRET = "test-secret-shared-with-broker";
const NOW = 1_700_000_000; // fixed "current time" (unix seconds) for deterministic expiry checks.

/** Mint a token granting `scopes`, expiring `ttl` seconds after NOW (default: +1h). */
function tokenFor(scopes: string[], ttl = 3600, sub?: string): string {
  const claims: CapabilityClaims = { scopes, exp: NOW + ttl, ...(sub ? { sub } : {}) };
  return signCapability(claims, SECRET);
}

// --- verifyCapability: happy path -------------------------------------------

test("verifyCapability accepts a valid, unexpired, scoped token", () => {
  const token = tokenFor(["worldview:watch"], 3600, "agent-1");
  const res = verifyCapability(token, "worldview:watch", { secret: SECRET, now: NOW });
  assert.equal(res.ok, true);
  if (res.ok) {
    assert.deepEqual(res.claims.scopes, ["worldview:watch"]);
    assert.equal(res.claims.sub, "agent-1");
  }
});

test("verifyCapability honours the 'worldview:*' wildcard scope", () => {
  const token = tokenFor(["worldview:*"]);
  const res = verifyCapability(token, "worldview:reconstruct", { secret: SECRET, now: NOW });
  assert.equal(res.ok, true);
});

// --- verifyCapability: deny paths (must never throw) ------------------------

test("verifyCapability denies when no secret is configured (fail closed)", () => {
  const token = tokenFor(["worldview:watch"]);
  const res = verifyCapability(token, "worldview:watch", { secret: undefined, now: NOW });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "no-secret-configured");
});

test("verifyCapability denies a token signed with a different secret (bad signature)", () => {
  const token = signCapability({ scopes: ["worldview:watch"], exp: NOW + 3600 }, "WRONG-secret");
  const res = verifyCapability(token, "worldview:watch", { secret: SECRET, now: NOW });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "bad-signature");
});

test("verifyCapability denies a tampered payload (signature no longer matches)", () => {
  // Forge a payload but keep someone else's signature -> bad-signature, never trusted.
  const forgedPayload = Buffer.from(
    JSON.stringify({ scopes: ["worldview:*"], exp: NOW + 3600 }),
    "utf8",
  ).toString("base64url");
  const staleSig = signPayload("not-this-payload", SECRET);
  const res = verifyCapability(`${forgedPayload}.${staleSig}`, "worldview:watch", {
    secret: SECRET,
    now: NOW,
  });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "bad-signature");
});

test("verifyCapability denies an expired token", () => {
  const token = tokenFor(["worldview:watch"], -10); // exp in the past relative to NOW
  const res = verifyCapability(token, "worldview:watch", { secret: SECRET, now: NOW });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "expired");
});

test("verifyCapability denies a token missing the required scope", () => {
  const token = tokenFor(["worldview:reconstruct"]);
  const res = verifyCapability(token, "worldview:watch", { secret: SECRET, now: NOW });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "missing-scope");
});

test("verifyCapability denies an empty/undefined token without throwing", () => {
  for (const bad of [undefined, "", "   "]) {
    const res = verifyCapability(bad, "worldview:watch", { secret: SECRET, now: NOW });
    assert.equal(res.ok, false);
    if (!res.ok) assert.equal(res.reason, "missing-token");
  }
});

test("verifyCapability denies a structurally malformed token without throwing", () => {
  for (const bad of ["no-dot-separator", "a.b.c", "onlyhalf.", ".onlysig"]) {
    const res = verifyCapability(bad, "worldview:watch", { secret: SECRET, now: NOW });
    assert.equal(res.ok, false);
  }
});

test("verifyCapability denies a token whose payload is not valid JSON/claims", () => {
  // Valid signature over a non-JSON payload -> malformed-payload (still no throw).
  const payload = Buffer.from("this-is-not-json", "utf8").toString("base64url");
  const sig = signPayload(payload, SECRET);
  const res = verifyCapability(`${payload}.${sig}`, "worldview:watch", { secret: SECRET, now: NOW });
  assert.equal(res.ok, false);
  if (!res.ok) assert.equal(res.reason, "malformed-payload");
});

// --- audit ------------------------------------------------------------------

test("audit emits structured JSON to the injected sink (not stdout)", () => {
  const lines: string[] = [];
  const entry: AuditEntry = { tool: "watch_aoi", decision: "deny", reason: "missing-scope" };
  const returned = audit(entry, (line) => lines.push(line));

  assert.equal(lines.length, 1);
  assert.equal(lines[0], returned);
  assert.ok(returned.endsWith("\n"), "audit line should be newline-terminated");
  const rec = JSON.parse(returned);
  assert.equal(rec.tool, "watch_aoi");
  assert.equal(rec.decision, "deny");
  assert.equal(rec.reason, "missing-scope");
  assert.equal(typeof rec.ts, "string");
});

test("audit omits absent optional fields", () => {
  const lines: string[] = [];
  audit({ tool: "reconstruct_event", decision: "allow" }, (line) => lines.push(line));
  const rec = JSON.parse(lines[0]!);
  assert.equal(rec.decision, "allow");
  assert.equal("reason" in rec, false);
  assert.equal("sub" in rec, false);
});
