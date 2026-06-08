import test from "node:test";
import assert from "node:assert/strict";
import {
  can,
  inScope,
  ruleFor,
  objectAoiId,
  AOI_SCOPED_OBJECT_TYPES,
  type Principal,
} from "../src/auth/rbac.js";

// Unit tests for the pure RBAC + ABAC core (ticket H19.4.2): the role->permission matrix, AOI scoping,
// the route->permission mapping, and the object-AOI extractor.

test("viewer can read but cannot write or read audit", () => {
  assert.ok(can("viewer", "read:history"));
  assert.ok(can("viewer", "read:recon"));
  assert.ok(can("viewer", "read:ontology"));
  assert.equal(can("viewer", "write:ontology-action"), false);
  assert.equal(can("viewer", "read:audit"), false);
  assert.equal(can("viewer", "admin"), false);
});

test("analyst can read + write:ontology-action but not read:audit/admin", () => {
  assert.ok(can("analyst", "read:ontology"));
  assert.ok(can("analyst", "write:ontology-action"));
  assert.equal(can("analyst", "read:audit"), false);
  assert.equal(can("analyst", "admin"), false);
});

test("admin holds every permission (incl read:audit + admin)", () => {
  for (const perm of [
    "read:history",
    "read:live",
    "read:provenance",
    "read:recon",
    "read:ontology",
    "write:ontology-action",
    "read:audit",
    "admin",
  ] as const) {
    assert.ok(can("admin", perm), `admin should hold ${perm}`);
  }
});

test("inScope: admin and wildcard bypass scoping", () => {
  const admin: Principal = { sub: "a", role: "admin", aois: ["aoi-x"] };
  const wild: Principal = { sub: "w", role: "viewer", aois: ["*"] };
  assert.ok(inScope(admin, "aoi-anything"));
  assert.ok(inScope(wild, "aoi-anything"));
});

test("inScope: a restricted principal only sees its AOIs", () => {
  const p: Principal = { sub: "v", role: "analyst", aois: ["aoi-strait", "7"] };
  assert.ok(inScope(p, "aoi-strait"));
  assert.ok(inScope(p, "7"));
  assert.ok(inScope(p, 7 as unknown as string)); // numeric geofence id coerced to string
  assert.equal(inScope(p, "aoi-other"), false);
});

test("inScope: a datum with no AOI is always visible (scoping only narrows AOI-bearing data)", () => {
  const p: Principal = { sub: "v", role: "viewer", aois: ["aoi-strait"] };
  assert.ok(inScope(p, null));
  assert.ok(inScope(p, undefined));
  assert.ok(inScope(p, ""));
});

test("ruleFor maps methods+paths to permissions and treats /health as public", () => {
  assert.equal(ruleFor("GET", "/health"), null);
  assert.equal(ruleFor("GET", "/ready"), null);
  assert.equal(ruleFor("GET", "/recon/windows")?.permission, "read:recon");
  assert.equal(ruleFor("GET", "/recon/windows")?.requiresScope, true);
  assert.equal(ruleFor("GET", "/ontology/audit/verify")?.permission, "read:audit");
  assert.equal(ruleFor("GET", "/ontology/actions")?.permission, "read:audit");
  assert.equal(
    ruleFor("POST", "/ontology/objects/:type/:id/actions/:action")?.permission,
    "write:ontology-action",
  );
  assert.equal(ruleFor("GET", "/ontology/objects/:type")?.permission, "read:ontology");
});

test("objectAoiId extracts the scoping AOI per type; non-AOI types return null", () => {
  assert.equal(objectAoiId("Aoi", { id: "7", properties: {} }), "7");
  assert.equal(objectAoiId("ReconWindow", { id: "x", properties: { aoiId: "aoi-strait" } }), "aoi-strait");
  assert.equal(
    objectAoiId("DarkVesselEvent", { id: "y", properties: { geofenceId: "12" } }),
    "12",
  );
  assert.equal(objectAoiId("Aircraft", { id: "4ca7b3", properties: {} }), null);
});

test("AOI_SCOPED_OBJECT_TYPES covers exactly the AOI-bearing types", () => {
  assert.ok(AOI_SCOPED_OBJECT_TYPES.has("Aoi"));
  assert.ok(AOI_SCOPED_OBJECT_TYPES.has("ReconWindow"));
  assert.ok(AOI_SCOPED_OBJECT_TYPES.has("DarkVesselEvent"));
  assert.equal(AOI_SCOPED_OBJECT_TYPES.has("Aircraft"), false);
});
