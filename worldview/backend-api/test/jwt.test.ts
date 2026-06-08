import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { signToken, verifyToken, isRole, type Claims } from "../src/auth/jwt.js";

// Unit tests for the HS256 JWT primitive (ticket H19.4.2). Pure: no Fastify, no I/O. Covers the
// round-trip plus the fail-CLOSED rejections (expired / bad-sig / malformed / wrong-alg / bad claims).

const SECRET = "test-secret-key";
const NOW = 1_700_000_000; // fixed UNIX seconds so exp/iat are deterministic.

test("signToken + verifyToken round-trip preserves claims", () => {
  const token = signToken({ sub: "u1", role: "analyst", aois: ["aoi-strait"] }, SECRET, 3600, NOW);
  const res = verifyToken(token, SECRET, NOW);
  assert.equal(res.ok, true);
  assert.ok(res.ok && res.claims.sub === "u1");
  assert.ok(res.ok && res.claims.role === "analyst");
  assert.ok(res.ok && res.claims.exp === NOW + 3600);
  assert.ok(res.ok && res.claims.iat === NOW);
  assert.deepEqual(res.ok && res.claims.aois, ["aoi-strait"]);
});

test("verifyToken rejects an expired token", () => {
  const token = signToken({ sub: "u1", role: "viewer" }, SECRET, 60, NOW);
  // Evaluate 'now' AFTER exp (NOW+60).
  const res = verifyToken(token, SECRET, NOW + 61);
  assert.equal(res.ok, false);
  assert.ok(!res.ok && res.reason === "expired");
});

test("verifyToken accepts a token exactly before expiry and rejects at/after exp (UTC seconds)", () => {
  const token = signToken({ sub: "u1", role: "viewer" }, SECRET, 60, NOW);
  assert.equal(verifyToken(token, SECRET, NOW + 59).ok, true);
  // now === exp is treated as expired (>=).
  assert.equal(verifyToken(token, SECRET, NOW + 60).ok, false);
});

test("verifyToken rejects a tampered signature (wrong secret)", () => {
  const token = signToken({ sub: "u1", role: "admin" }, SECRET, 3600, NOW);
  const res = verifyToken(token, "wrong-secret", NOW);
  assert.equal(res.ok, false);
  assert.ok(!res.ok && res.reason === "bad signature");
});

test("verifyToken rejects a payload mutated after signing (bad signature)", () => {
  const token = signToken({ sub: "u1", role: "viewer" }, SECRET, 3600, NOW);
  const parts = token.split(".");
  // Re-encode a tampered payload (escalate role) without re-signing.
  const tampered = Buffer.from(JSON.stringify({ sub: "u1", role: "admin" }), "utf8")
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  const forged = `${parts[0]}.${tampered}.${parts[2]}`;
  assert.equal(verifyToken(forged, SECRET, NOW).ok, false);
});

test("verifyToken rejects malformed tokens (wrong segment count / empty)", () => {
  assert.equal(verifyToken("", SECRET, NOW).ok, false);
  assert.equal(verifyToken("a.b", SECRET, NOW).ok, false);
  assert.equal(verifyToken("a.b.c.d", SECRET, NOW).ok, false);
});

test("verifyToken rejects a non-HS256 alg header (alg-confusion guard)", () => {
  // Craft a 'none'-alg header with a real HS256 signature so only the alg header can reject it.
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" }), "utf8")
    .toString("base64url");
  const payload = Buffer.from(JSON.stringify({ sub: "u1", role: "admin", exp: NOW + 60 }), "utf8")
    .toString("base64url");
  const sig = createHmac("sha256", SECRET)
    .update(`${header}.${payload}`)
    .digest("base64url");
  const res = verifyToken(`${header}.${payload}.${sig}`, SECRET, NOW);
  assert.equal(res.ok, false);
  assert.ok(!res.ok && res.reason === "unsupported alg");
});

test("verifyToken rejects an invalid role claim", () => {
  const token = signToken({ sub: "u1", role: "superuser" as unknown as Claims["role"] }, SECRET, 3600, NOW);
  const res = verifyToken(token, SECRET, NOW);
  assert.equal(res.ok, false);
  assert.ok(!res.ok && res.reason === "invalid role");
});

test("verifyToken rejects a missing sub", () => {
  const token = signToken({ sub: "", role: "viewer" }, SECRET, 3600, NOW);
  assert.equal(verifyToken(token, SECRET, NOW).ok, false);
});

test("verifyToken rejects a non-string-array aois claim", () => {
  const token = signToken(
    { sub: "u1", role: "viewer", aois: [1, 2] as unknown as string[] },
    SECRET,
    3600,
    NOW,
  );
  const res = verifyToken(token, SECRET, NOW);
  assert.equal(res.ok, false);
  assert.ok(!res.ok && res.reason === "invalid aois");
});

test("isRole guards the three roles", () => {
  assert.ok(isRole("viewer"));
  assert.ok(isRole("analyst"));
  assert.ok(isRole("admin"));
  assert.equal(isRole("root"), false);
  assert.equal(isRole(undefined), false);
});
