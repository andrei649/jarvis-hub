import test from "node:test";
import assert from "node:assert/strict";
import Fastify, { type FastifyInstance } from "fastify";
import { config } from "../src/config.js";
import { registerGuard } from "../src/auth/guard.js";
import { reconRoutes } from "../src/routes/recon.js";
import { ontologyRoutes } from "../src/routes/ontology.js";
import { healthRoutes } from "../src/routes/health.js";
import { signToken } from "../src/auth/jwt.js";
import { getPool } from "../src/plugins/db.js";

// Route-level guard tests (ticket H19.4.2). These exercise the CENTRAL onRequest guard end-to-end via
// app.inject: with auth ENABLED (a secret set + tokens minted by signToken) and DISABLED (back-compat).
// Mirrors the repo's no-live-DB style: where a handler touches the pool we stub pool.query so scoping
// can be observed without Postgres.

const SECRET = "route-test-secret";

// Build an app with the guard + the routes under test. The guard reads config.authSecret at register
// time, so the caller sets/clears config.authSecret around each test.
async function build(): Promise<FastifyInstance> {
  const app = Fastify();
  await registerGuard(app);
  await app.register(healthRoutes);
  await app.register(reconRoutes);
  await app.register(ontologyRoutes);
  await app.ready();
  return app;
}

function bearer(token: string): Record<string, string> {
  return { authorization: `Bearer ${token}` };
}

// Stub the shared pool's query so /recon/windows + ontology reads return canned rows. recon's
// upcomingWindows selects aoi_id (snake_case) rows; ontology list/get returns dim/table rows.
function stubQuery(handler: (sql: string, params: unknown[]) => { rows: unknown[]; rowCount: number }) {
  const pool = getPool();
  const original = pool.query;
  (pool as unknown as { query: unknown }).query = async (sql: string, params: unknown[] = []) =>
    handler(sql, params);
  return () => {
    (pool as unknown as { query: unknown }).query = original;
  };
}

// ---------------------------------------------------------------------------
// AUTH DISABLED — back-compat: everything open, no token needed.
// ---------------------------------------------------------------------------
test("auth DISABLED: protected routes work with no token (back-compat)", async () => {
  config.authSecret = "";
  const restore = stubQuery(() => ({ rows: [], rowCount: 0 }));
  try {
    const app = await build();
    const health = await app.inject({ method: "GET", url: "/health" });
    assert.equal(health.statusCode, 200);
    const windows = await app.inject({ method: "GET", url: "/recon/windows" });
    assert.equal(windows.statusCode, 200);
    const types = await app.inject({ method: "GET", url: "/ontology/types" });
    assert.equal(types.statusCode, 200);
    // The audited POST works without a token in open mode too.
    const action = await app.inject({
      method: "POST",
      url: "/ontology/objects/Aircraft/4ca7b3/actions/annotate",
      payload: { note: "x" },
    });
    // 200 (audited) — stubQuery returns empty rows; the route still completes its happy path.
    assert.notEqual(action.statusCode, 401);
    assert.notEqual(action.statusCode, 403);
    await app.close();
  } finally {
    restore();
  }
});

// ---------------------------------------------------------------------------
// AUTH ENABLED — fail-CLOSED + RBAC + ABAC.
// ---------------------------------------------------------------------------
test("auth ENABLED: /health stays public (no token)", async () => {
  config.authSecret = SECRET;
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/health" });
    assert.equal(res.statusCode, 200);
    await app.close();
  } finally {
    config.authSecret = "";
  }
});

test("auth ENABLED: a protected route with no token is 401", async () => {
  config.authSecret = SECRET;
  try {
    const app = await build();
    const res = await app.inject({ method: "GET", url: "/recon/alerts" });
    assert.equal(res.statusCode, 401);
    assert.match(res.json().reason, /missing bearer/);
    await app.close();
  } finally {
    config.authSecret = "";
  }
});

test("auth ENABLED: a bad/expired token is 401", async () => {
  config.authSecret = SECRET;
  const restore = stubQuery(() => ({ rows: [], rowCount: 0 }));
  try {
    const app = await build();
    const garbage = await app.inject({
      method: "GET",
      url: "/recon/alerts",
      headers: bearer("not-a-jwt"),
    });
    assert.equal(garbage.statusCode, 401);
    // Token signed with the WRONG secret → bad signature → 401.
    const forged = signToken({ sub: "u", role: "admin" }, "other-secret");
    const wrong = await app.inject({
      method: "GET",
      url: "/recon/alerts",
      headers: bearer(forged),
    });
    assert.equal(wrong.statusCode, 401);
    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: viewer is 403 on the write action (RBAC)", async () => {
  config.authSecret = SECRET;
  const restore = stubQuery(() => ({ rows: [], rowCount: 0 }));
  try {
    const app = await build();
    const token = signToken({ sub: "v", role: "viewer" }, SECRET);
    const res = await app.inject({
      method: "POST",
      url: "/ontology/objects/Aircraft/4ca7b3/actions/annotate",
      headers: bearer(token),
      payload: { note: "x" },
    });
    assert.equal(res.statusCode, 403);
    assert.match(res.json().reason, /write:ontology-action/);
    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: viewer is 403 on the audit log (RBAC read:audit)", async () => {
  config.authSecret = SECRET;
  try {
    const app = await build();
    const token = signToken({ sub: "v", role: "viewer" }, SECRET);
    const res = await app.inject({
      method: "GET",
      url: "/ontology/audit/verify",
      headers: bearer(token),
    });
    assert.equal(res.statusCode, 403);
    await app.close();
  } finally {
    config.authSecret = "";
  }
});

test("auth ENABLED: admin is 200 on /ontology/audit/verify (read:audit)", async () => {
  config.authSecret = SECRET;
  // verifyAuditChain selects the audit rows; an empty chain verifies ok.
  const restore = stubQuery(() => ({ rows: [], rowCount: 0 }));
  try {
    const app = await build();
    const token = signToken({ sub: "root", role: "admin" }, SECRET);
    const res = await app.inject({
      method: "GET",
      url: "/ontology/audit/verify",
      headers: bearer(token),
    });
    assert.equal(res.statusCode, 200);
    assert.equal(res.json().ok, true);
    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});

test("auth ENABLED: analyst can annotate (200) but is 403 on an out-of-scope AOI window", async () => {
  config.authSecret = SECRET;
  // The annotate path writes via pool.connect (transaction) + pool.query; stub both like the ontology
  // route tests do. recon's upcomingWindows returns rows we can scope-filter.
  const pool = getPool();
  const originalQuery = pool.query;
  const originalConnect = pool.connect;
  const handle = async (sql: string) => {
    if (/recon_windows/.test(sql)) {
      // Two windows: one in-scope (aoi-strait), one out (aoi-other).
      return {
        rows: [
          { norad_id: 1, aoi_id: "aoi-strait", sensor_type: "optical", t_ingress: 1, t_peak: 2, t_egress: 3, min_distance_km: 5, sunlit_at_peak: true, quality: 0.9 },
          { norad_id: 2, aoi_id: "aoi-other", sensor_type: "optical", t_ingress: 1, t_peak: 2, t_egress: 3, min_distance_km: 5, sunlit_at_peak: true, quality: 0.9 },
        ],
        rowCount: 2,
      };
    }
    if (/ontology_annotations/.test(sql)) return { rows: [{ id: 9 }], rowCount: 1 };
    if (/nextval/.test(sql)) return { rows: [{ id: 1, ts: 1, tip_hash: null }], rowCount: 1 };
    if (/INSERT INTO ontology_actions/.test(sql)) {
      return { rows: [{ id: 1, ts: 1, actor: "an", object_type: "Aircraft", object_id: "x", action: "annotate", params: {}, result: {}, source: "api", prev_hash: null, entry_hash: "h" }], rowCount: 1 };
    }
    return { rows: [], rowCount: 0 };
  };
  (pool as unknown as { query: unknown }).query = handle;
  (pool as unknown as { connect: unknown }).connect = async () => ({ query: handle, release: () => {} });
  try {
    const app = await build();
    // analyst scoped to aoi-strait only.
    const token = signToken({ sub: "an", role: "analyst", aois: ["aoi-strait"] }, SECRET);

    // annotate → 200 (analyst holds write:ontology-action).
    const annotate = await app.inject({
      method: "POST",
      url: "/ontology/objects/Aircraft/4ca7b3/actions/annotate",
      headers: bearer(token),
      payload: { note: "watch" },
    });
    assert.equal(annotate.statusCode, 200);

    // Asking for a specific OUT-of-scope AOI → 403.
    const denied = await app.inject({
      method: "GET",
      url: "/recon/windows?aoi=aoi-other",
      headers: bearer(token),
    });
    assert.equal(denied.statusCode, 403);

    // No aoi filter → 200 but the result is FILTERED to in-scope AOIs only.
    const filtered = await app.inject({
      method: "GET",
      url: "/recon/windows",
      headers: bearer(token),
    });
    assert.equal(filtered.statusCode, 200);
    const windows = filtered.json().windows as { aoi_id: string }[];
    assert.equal(windows.length, 1);
    assert.equal(windows[0]!.aoi_id, "aoi-strait");
    await app.close();
  } finally {
    (pool as unknown as { query: unknown }).query = originalQuery;
    (pool as unknown as { connect: unknown }).connect = originalConnect;
    config.authSecret = "";
  }
});

test("auth ENABLED: ABAC scopes ontology AOI reads — list filtered, out-of-scope single is 403", async () => {
  config.authSecret = SECRET;
  // Aoi is a geofences table type; list returns two geofences (ids 7 and 8); the principal is scoped to
  // geofence "7" only. Single get of id 8 → 403; list → only id 7.
  const restore = stubQuery((sql) => {
    if (/geofences/.test(sql) && /WHERE \(id\) = \$1/.test(sql)) {
      // getObject path — return whichever id was asked (id 8 here triggers the out-of-scope test).
      return { rows: [{ id: 8, name: "Strait B", category: "aoi", dark_gap_seconds: 60, created_at: 1 }], rowCount: 1 };
    }
    if (/geofences/.test(sql)) {
      return {
        rows: [
          { id: 7, name: "Strait A", category: "aoi", dark_gap_seconds: 60, created_at: 1 },
          { id: 8, name: "Strait B", category: "aoi", dark_gap_seconds: 60, created_at: 1 },
        ],
        rowCount: 2,
      };
    }
    return { rows: [], rowCount: 0 };
  });
  try {
    const app = await build();
    const token = signToken({ sub: "v", role: "viewer", aois: ["7"] }, SECRET);

    const list = await app.inject({
      method: "GET",
      url: "/ontology/objects/Aoi",
      headers: bearer(token),
    });
    assert.equal(list.statusCode, 200);
    const objects = list.json().objects as { id: string }[];
    assert.equal(objects.length, 1);
    assert.equal(objects[0]!.id, "7");

    const single = await app.inject({
      method: "GET",
      url: "/ontology/objects/Aoi/8",
      headers: bearer(token),
    });
    assert.equal(single.statusCode, 403);
    await app.close();
  } finally {
    restore();
    config.authSecret = "";
  }
});
