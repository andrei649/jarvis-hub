import { test, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Guards the deck/luma shim pin (H19.5.1). lib/deckExtensionsShim.mjs aliases ClipExtension out of
// @deck.gl/extensions against the pinned @deck.gl/core Layer class. If @deck.gl/extensions (or
// @deck.gl/mesh-layers) is left to float on ^9.0.0 it hoists to a 9.3.x copy whose Layer class no
// longer matches 9.0.27 core — exactly the fragility this pin removes. Read the *resolved*
// versions from node_modules so a future float (an unpinned override / lockfile drift) trips here.
//
// node_modules lives at the worldview root (monorepo install), one level up from frontend/.
const root = fileURLToPath(new URL("../../..", import.meta.url));

function resolvedVersion(pkg: string): string {
  const json = JSON.parse(readFileSync(`${root}/node_modules/${pkg}/package.json`, "utf8"));
  return json.version as string;
}

test("@deck.gl/extensions resolves to the same version as @deck.gl/core", () => {
  expect(resolvedVersion("@deck.gl/extensions")).toBe(resolvedVersion("@deck.gl/core"));
});

test("@deck.gl/mesh-layers resolves to the same version as @deck.gl/core", () => {
  expect(resolvedVersion("@deck.gl/mesh-layers")).toBe(resolvedVersion("@deck.gl/core"));
});

test("@deck.gl/core is pinned to 9.0.27", () => {
  expect(resolvedVersion("@deck.gl/core")).toBe("9.0.27");
});
