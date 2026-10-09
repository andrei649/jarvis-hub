# Read-only task mediation status

- Generated: 2026-10-09 UTC.
- Goal: expose the existing queue evidence verification to administrators and show
  its actual state in Autonomy Control without changing authority or enabling B7.
- Base/head before edits: `724969839b4660dc09a37abce4964b13ae928f9f`.
- Branch: `codex/task-mediation-status-20261009`.
- Source context: DRA-59 still explicitly lists missing route/HUD visibility.
  `TaskQueue.verified_mediation_stats()` verifies the persisted chain and detached
  head; its invalid result contains placeholder zeros. Its helpers only read here.
  The initialized queue's `mediation_mode` is the effective mode, not a new env read.

## Contract

Add admin-guarded `GET /autonomy/mediation`, with no-cache responses and no network,
enqueue, approval, mode update, receipt creation or raw event disclosure. Use the
existing initialized queue. A synchronous handler lets FastAPI run verification
in its worker pool rather than blocking the event loop with a chain scan.

The successful JSON response is exactly:

```json
{
  "mode": "off",
  "valid": true,
  "stats": {
    "authorized_enqueue": 0,
    "governed": 0,
    "refused_unmediated": 0,
    "ungoverned_detected": 0
  }
}
```

Mode is `off`, `hold` or `enforce`. For `valid: false`, return `stats: null`, never
the queue's placeholder zero counts. Missing queue, verification exception, unknown
mode or malformed valid snapshot return generic 503 without raw exception details.
Valid counters must be actual nonnegative integers (booleans are not counters);
copy only the four named fields and never expose additional internal values.

Add a read-only section to the existing Autonomy Control panel. Its admin GET uses
the existing credential transport and reload action. Display the effective mode,
evidence verification and four event counts only from a complete valid snapshot.
Off/hold remain explicit, even when the evidence chain is valid. Invalid evidence,
malformed response, loading, 401/403/503 and network failures have no numeric
fallback; clear previous numbers during refresh and after errors. No new controls
to enable mediation, approve work or fetch raw events. Explain that counts describe
verified recorded events, not coverage of every task or operational acceptance.

## Scope and proof

- Backend writer: `agents/core/routers/autonomy.py` and a new focused HTTP test.
- Frontend writer: `frontend/src/panels/autonomy-legacy.tsx` and its test file.
- Coordinator: plan, parity/route snapshots, generated API/status/type artifacts,
  bounded BACKLOG update and reviewed evidence pins. No shared-file writers.
- Red-first backend cases: admin guard, missing/uninitialized queue, exact valid
  projection, invalid evidence, malformed types, exceptions, no writes/raw data,
  and real signed queue plus tampered evidence.
- Frontend cases: actual admin header, three modes, four counts, invalid/loading/
  malformed/error snapshots, stale data hidden on refresh, no writes.
- Integration: task mediation suites, route/auth/OpenAPI/HUD/lifespan guards,
  targeted frontend tests and build/type checks; browser hard reload as practical.
- Rollback: revert this route, panel section, tests and delivery metadata together;
  no persisted schema/data change. No paid provider, device, push or deployment.
- Remaining: other real task kinds and producer migration, raw evidence inspection,
  native mobile status view and B7/program acceptance are separate backlog work.

Two implementation agents use gpt-6-sol/high. The coordinator owns interfaces and
integration; a gpt-6-luna/medium read-only inventory may inspect collateral pins.
Next action: implement the fixed contract independently on backend and frontend.

## Implemented checkpoint

The backend builder demonstrated 14 red 404 regressions before implementation;
its final new module has 15 cases. The focused mediation/route union passes
183/183 (7.917 seconds), including a real signed queue and corrupted signature,
strict projections, actual admin authentication and worker-thread execution. Its
read-only proof preserves SQLite total_changes and the detached head across GETs.
The frontend first had 15 new failures alongside 11 passing old cases, then
27/27 pass after implementation and the invalid-evidence refresh regression.
Independent cross-review found no Critical/Important issue; the backend reviewer
independently passed all15 new cases.

The route/OpenAPI/auth/HUD/lifespan/API-manual union passes42/42. Exactly one
admin GET is added to each runtime-derived route snapshot. Regenerating OpenAPI
TypeScript adds the new operation/two models and also catches up the earlier
implemented /v1/capabilities operation missing from generated types; no existing
wire contract changed. Build and application/E2E type checks pass. The generated
production bundle is included.

The complete default frontend suite passes **1,978/1,978** across223 files:
1,841 browser/HUD cases and137 native React host cases. No pending/todo/failure.
Report: /workspace/scratch/task-mediation-frontend-full.json. Real Chromium using
the production bundle passes2/2 at1280px and390px, checking hard reload in all
three modes, exact admin header, invalid/503 count removal, no business writes,
no page errors and section bounds. Screenshots were inspected. API responses in
this browser lane are fixtures; the backend HTTP suite separately verifies the
real signed queue. Config: frontend/playwright.mediation.config.ts.

Collateral review refreshed only6 previously current pins in H277/H487: the
router, three route snapshots and generated TS. All29 existing router symbols
have identical ASTs; only the new models/route are added. Four already-stale pins
(H139/H146/H449 generated TS andH477 routeauth) remain unchanged. No assessment
status, summary or remaining claim is changed. Native UI remains H18.32.

Backend collection is21,129 (+15), frontend1,978 (+16), mobile284, routes555.
Work is local, with no provider/device/publication.

Full backend checkpoint at `4625a1b` returned21,091 passed,37 skipped, one failure
and zero errors (275.149 seconds). The one failure was the existing architecture
guard `test_no_router_reinlines_the_component_503_preamble`: the new handler
hand-rolled availability resolution instead of using `require_component`. It
reproduced in isolation. Correction `9d32c13` uses that existing helper while
retaining this route's no-store generic503, response projection and admin guard.
The helper's conservative falsy-orchestrator refusal matches other routers.
The assertion and its allowlist are unchanged. Only the two current router pins
were refreshed again; independent review found no blocker.

After the correction, the complete new API, component-sweep, autonomy HTTP,
route/auth/OpenAPI/HUD/manual and lifespan union passes101/101 in5.023 seconds.
The failing node is included and passing. Exact count and generated freshness
gates pass. The full suite was not repeated after this narrowly scoped repair;
the initial full result remains a failed checkpoint. Frontend source/assets are
byte-identical to the fully tested checkpoint. See the
[integration evidence](../project-task-mediation-integration-20261009.md).
