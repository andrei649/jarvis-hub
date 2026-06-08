import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { signCapability, verifyCapability } from "../src/auth.js";

// Cross-language pinning test (ticket H19.3.2). The SAME fixture
// (test/fixtures/capability-vectors.json) is asserted by BOTH this TS suite AND the JARVIS-side
// Python suite (tests/test_worldview_mcp_capability.py). It proves the MCP server's verifier and
// JARVIS's minter (agents/core/security/worldview_mcp.py) speak a byte-identical token format: if
// either side's encoding (claim key order, compact JSON, base64url-no-pad, HMAC-over-payload-string)
// drifts, the recomputed token stops matching the frozen `token` and CI fails on that side. So the
// two independent security implementations can never silently diverge.

interface Vector {
  name: string;
  claims: { scopes: string[]; exp: number; sub?: string };
  token: string;
  grants: string[];
  denies: string[];
}
interface Fixture {
  secret: string;
  vectors: Vector[];
}

const fixturePath = fileURLToPath(new URL("./fixtures/capability-vectors.json", import.meta.url));
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as Fixture;

for (const v of fixture.vectors) {
  test(`vector '${v.name}': signCapability reproduces the frozen token byte-for-byte`, () => {
    // Claims are serialized in declaration order {scopes, exp, sub}; the fixture stores them the same
    // way, so JSON.stringify must yield the exact payload segment the Python side produced.
    const token = signCapability(v.claims, fixture.secret);
    assert.equal(token, v.token, "TS-minted token diverged from the shared cross-language vector");
  });

  test(`vector '${v.name}': verifyCapability accepts the frozen token for each granted scope`, () => {
    const now = v.claims.exp - 1; // unexpired by one second
    for (const scope of v.grants) {
      const res = verifyCapability(v.token, scope, { secret: fixture.secret, now });
      assert.ok(res.ok, `expected scope '${scope}' to be granted: ${res.ok ? "" : res.reason}`);
      if (res.ok) {
        assert.deepEqual(res.claims.scopes, v.claims.scopes);
        assert.equal(res.claims.exp, v.claims.exp);
        assert.equal(res.claims.sub, v.claims.sub);
      }
    }
  });

  test(`vector '${v.name}': verifyCapability denies un-granted scopes (missing-scope)`, () => {
    const now = v.claims.exp - 1;
    for (const scope of v.denies) {
      const res = verifyCapability(v.token, scope, { secret: fixture.secret, now });
      assert.equal(res.ok, false);
      if (!res.ok) assert.equal(res.reason, "missing-scope");
    }
  });

  test(`vector '${v.name}': the frozen token is rejected once expired`, () => {
    const res = verifyCapability(v.token, v.grants[0]!, { secret: fixture.secret, now: v.claims.exp });
    assert.equal(res.ok, false);
    if (!res.ok) assert.equal(res.reason, "expired");
  });

  test(`vector '${v.name}': a wrong secret yields bad-signature, not a crash`, () => {
    const res = verifyCapability(v.token, v.grants[0]!, { secret: "not-the-shared-secret", now: v.claims.exp - 1 });
    assert.equal(res.ok, false);
    if (!res.ok) assert.equal(res.reason, "bad-signature");
  });
}
