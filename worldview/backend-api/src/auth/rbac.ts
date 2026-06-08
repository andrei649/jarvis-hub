import type { Role } from "./jwt.js";

// AuthZ policy (ticket H19.4.2) — the pure RBAC + ABAC core. RBAC: a static role->permission matrix
// and `can(role, permission)`. ABAC: `inScope(principal, aoiId)` decides whether a principal whose
// token restricts `aois` may see an AOI-scoped datum. Plus the declarative route->permission mapping
// the request guard consults. Everything here is data + pure functions (no Fastify, no I/O) so it's
// trivially unit-testable and the guard stays thin.

// The permission vocabulary. Reads are per-domain so a future per-domain role is easy; `write:
// ontology-action` gates the one mutating endpoint (annotate/watch); `read:audit` gates the audit
// log/verify; `admin` is the catch-all super-permission.
export type Permission =
  | "read:history"
  | "read:live"
  | "read:provenance"
  | "read:recon"
  | "read:ontology"
  | "write:ontology-action"
  | "read:cases"
  | "write:cases"
  | "read:audit"
  | "admin";

// The role->permission matrix. viewer = reads only; analyst = reads + write:ontology-action; admin =
// everything (incl read:audit + admin). Listed explicitly (not derived) so the policy is auditable at
// a glance.
// viewer reads (incl. read:cases — a viewer may READ shared case files). analyst additionally writes
// (ontology actions + case collaboration). admin holds everything.
const VIEWER_READS: Permission[] = [
  "read:history",
  "read:live",
  "read:provenance",
  "read:recon",
  "read:ontology",
  "read:cases",
];

export const ROLE_PERMISSIONS: Record<Role, ReadonlySet<Permission>> = {
  viewer: new Set<Permission>(VIEWER_READS),
  analyst: new Set<Permission>([...VIEWER_READS, "write:ontology-action", "write:cases"]),
  admin: new Set<Permission>([
    ...VIEWER_READS,
    "write:ontology-action",
    "write:cases",
    "read:audit",
    "admin",
  ]),
};

/** Whether `role` holds `permission`. admin holds `admin`, which short-circuits to true for all. */
export function can(role: Role, permission: Permission): boolean {
  const perms = ROLE_PERMISSIONS[role];
  if (!perms) return false;
  return perms.has("admin") || perms.has(permission);
}

// The resolved request principal attached to every request by the guard. `aois` is the allowed scope:
// `["*"]` (or admin) means unrestricted. Kept here (not in jwt.ts) because it's the AuthZ-side view of
// a verified token.
export interface Principal {
  sub: string;
  role: Role;
  aois: string[];
}

// The wildcard AOI scope token: a principal whose `aois` contains "*" sees every AOI.
export const AOI_WILDCARD = "*";

/** Whether `principal` may access data scoped to `aoiId`. admin and a `*` scope bypass scoping. */
export function inScope(principal: Principal, aoiId: string | null | undefined): boolean {
  if (principal.role === "admin") return true;
  if (principal.aois.includes(AOI_WILDCARD)) return true;
  // No AOI on the datum ⇒ not AOI-scoped ⇒ visible (scoping only narrows AOI-bearing data).
  if (aoiId == null || aoiId === "") return true;
  return principal.aois.includes(String(aoiId));
}

// ---------------------------------------------------------------------------
// ROUTE -> PERMISSION MAPPING. The guard matches the request's METHOD + Fastify routerPath against
// these rules (longest/most-specific match wins) to find the required permission. `/health` and
// `/ready` are intentionally ABSENT = public. `requiresScope` flags routes that additionally apply
// ABAC AOI scoping inside their handler (the guard only sets the principal; the handler filters).
// ---------------------------------------------------------------------------
export interface RouteRule {
  method: string;
  /** Fastify routerPath pattern (e.g. "/ontology/objects/:type/:id/actions/:action"). */
  path: string;
  permission: Permission;
  /** Whether the handler applies AOI scoping for AOI-bearing data (documentation/intent flag). */
  requiresScope?: boolean;
}

export const ROUTE_RULES: RouteRule[] = [
  // History / provenance / live — domain reads.
  { method: "GET", path: "/history/:layer", permission: "read:history" },
  { method: "GET", path: "/history/:layer/:entityId/track", permission: "read:history" },
  { method: "GET", path: "/provenance/:layer/:entityId", permission: "read:provenance" },
  { method: "GET", path: "/live", permission: "read:live" },

  // Recon — reads; /recon/windows is AOI-scoped (filtered to the principal's AOIs).
  { method: "GET", path: "/recon/windows", permission: "read:recon", requiresScope: true },
  { method: "GET", path: "/recon/alerts", permission: "read:recon" },

  // Ontology — the registry + projections are reads; audit log/verify need read:audit; the POST
  // action needs write:ontology-action. Object reads are AOI-scoped for AOI-bearing types.
  { method: "GET", path: "/ontology/types", permission: "read:ontology" },
  { method: "GET", path: "/ontology/actions", permission: "read:audit" },
  { method: "GET", path: "/ontology/audit/verify", permission: "read:audit" },
  { method: "GET", path: "/ontology/objects/:type", permission: "read:ontology", requiresScope: true },
  { method: "GET", path: "/ontology/objects/:type/:id", permission: "read:ontology", requiresScope: true },
  { method: "GET", path: "/ontology/objects/:type/:id/links", permission: "read:ontology" },
  {
    method: "POST",
    path: "/ontology/objects/:type/:id/actions/:action",
    permission: "write:ontology-action",
  },

  // Cases (ticket H19.4.5) — collaborative case files. Reads need read:cases (viewer+); every
  // mutation (create / status / members / items / comments) needs write:cases (analyst+). Membership
  // is an in-case role layer recorded in case_members; the RBAC permission gates the API itself.
  { method: "POST", path: "/cases", permission: "write:cases" },
  { method: "GET", path: "/cases", permission: "read:cases" },
  { method: "GET", path: "/cases/:id", permission: "read:cases" },
  { method: "PATCH", path: "/cases/:id", permission: "write:cases" },
  { method: "POST", path: "/cases/:id/members", permission: "write:cases" },
  { method: "GET", path: "/cases/:id/members", permission: "read:cases" },
  { method: "DELETE", path: "/cases/:id/members/:actor", permission: "write:cases" },
  { method: "POST", path: "/cases/:id/items", permission: "write:cases" },
  { method: "GET", path: "/cases/:id/items", permission: "read:cases" },
  { method: "POST", path: "/cases/:id/comments", permission: "write:cases" },
  { method: "GET", path: "/cases/:id/comments", permission: "read:cases" },
  { method: "GET", path: "/cases/:id/history", permission: "read:cases" },
];

/**
 * Find the rule for a METHOD + routerPath, or null when the route is public (no rule). Matching is
 * exact on method + Fastify routerPath; we index the most-specific (longest) matching path so the
 * parameterized `:type/:id` routes don't get shadowed by `:type`.
 */
export function ruleFor(method: string, routerPath: string): RouteRule | null {
  let best: RouteRule | null = null;
  for (const rule of ROUTE_RULES) {
    if (rule.method !== method) continue;
    if (rule.path !== routerPath) continue;
    if (!best || rule.path.length > best.path.length) best = rule;
  }
  return best;
}

// The set of ontology object types that ARE AOI-scoped (carry/resolve to an AOI id). Reads of these
// types are filtered/denied for an out-of-scope principal; other types (Aircraft/Vessel/Satellite)
// are not AOI-bound and pass through. Exported so the handler and tests share one source of truth.
export const AOI_SCOPED_OBJECT_TYPES: ReadonlySet<string> = new Set([
  "Aoi",
  "ReconWindow",
  "DarkVesselEvent",
]);

/**
 * Extract the AOI id an ontology object is scoped to, or null when the type isn't AOI-bound. For Aoi
 * the AOI id IS the object id; for ReconWindow/DarkVesselEvent it's the `aoiId`/`geofenceId` property.
 * Used by the ontology handler to scope object reads against `inScope`.
 */
export function objectAoiId(
  type: string,
  object: { id: string; properties: Record<string, unknown> },
): string | null {
  if (type === "Aoi") return object.id;
  if (type === "ReconWindow") {
    const a = object.properties.aoiId;
    return a == null ? null : String(a);
  }
  if (type === "DarkVesselEvent") {
    const g = object.properties.geofenceId;
    return g == null ? null : String(g);
  }
  return null;
}
