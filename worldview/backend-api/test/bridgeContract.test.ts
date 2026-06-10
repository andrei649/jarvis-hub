// WorldView bridge contract — provider side (twin of the hub's
// tests/test_worldview_bridge_contract.py). Asserts every endpoint promised in
// docs/contracts/worldview-bridge.md is actually registered (method + path) in the
// canonical route registry (auth/rbac.ts ROUTE_RULES) with a read permission — so a
// route rename/removal in WorldView fails CI here before it silently breaks Argus.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { ROUTE_RULES } from "../src/auth/rbac.js";

const here = dirname(fileURLToPath(import.meta.url));
const contractPath = join(here, "..", "..", "..", "docs", "contracts", "worldview-bridge.md");

function contractEndpoints(): Array<{ method: string; path: string }> {
  const text = readFileSync(contractPath, "utf-8");
  const block = text.match(/```yaml\n([\s\S]*?)```/);
  assert.ok(block, "contract yaml block missing from worldview-bridge.md");
  const endpoints: Array<{ method: string; path: string }> = [];
  const re = /-\s+method:\s+(\S+)\s*\n\s+path:\s+(\S+)/g;
  for (let m = re.exec(block![1]); m; m = re.exec(block![1])) {
    endpoints.push({ method: m[1], path: m[2] });
  }
  assert.ok(endpoints.length >= 6, `expected >=6 contract endpoints, got ${endpoints.length}`);
  return endpoints;
}

test("every bridge-contract endpoint is registered in ROUTE_RULES", () => {
  for (const ep of contractEndpoints()) {
    const rule = ROUTE_RULES.find((r) => r.method === ep.method && r.path === ep.path);
    assert.ok(
      rule,
      `${ep.method} ${ep.path} promised by docs/contracts/worldview-bridge.md is not in ROUTE_RULES — ` +
        "renaming/removing it breaks the JARVIS bridge (bump the contract version + fix both sides in one PR)",
    );
  }
});

test("bridge-contract endpoints carry read permissions only", () => {
  for (const ep of contractEndpoints()) {
    const rule = ROUTE_RULES.find((r) => r.method === ep.method && r.path === ep.path)!;
    assert.match(
      String(rule.permission),
      /^read:/,
      `${ep.path} must stay a read:* route — the hub bridge is read-only by contract`,
    );
  }
});
