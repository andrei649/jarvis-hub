# Admin EstopCard accessibility readiness

Generated 2026-10-09 UTC. Base: `917c10c0a684d67e841c909691a83b15bae502c4` on `codex/admin-a11y-readiness-20261009`.

Goal: make EstopCard's `/api/ops/estop` request lifecycle explicit in the DOM and require the Admin accessibility walk to wait for its settled state before axe. A failed or unavailable read is settled for scanning, but remains visibly unavailable; a pending read is never treated as ready because the DOM stopped changing. The walk retains its empty-surface and node/pending artifact evidence. Non-goal: claiming all Admin data, all mode surfaces, or accessibility itself is ready when this one card settles. The other Admin live-data refill remains a separate readiness gap.

Likely paths: `frontend/src/modes3.tsx`, `frontend/src/test/estop-card.test.tsx`, `frontend/e2e/a11y-modes.spec.ts`. Add a small shared wait helper only if useful. Tests: red-first component cases for pending/fulfilled/rejected/invalid read, with `aria-busy`; deterministic Playwright intercepted `/api/ops/estop` response held beyond the old 1600 ms DOM-quiet window, using the same wait helper as the production walk; then focused Vitest and frontend TypeScript checks. Root runs the full real-browser lane. No external provider or credential is needed. Rollback removes the readiness marker and wait hook together, restoring the old heuristic without data migration.

Proof at handoff: component tests were red (3 failures from missing marker and an empty response that stayed pending) before the source change; then 8/8 passed, including a deliberately held pause POST. Frontend and e2e TypeScript checks passed. Playwright collected six tests, including the delayed intercepted GET regression and a helper regression for explicit Admin ModeEmpty versus mounted Admin with a missing or pending marker; root owns execution against a rebuilt local `/v2` bundle and the backend fixture. The DOM marker reports `pending`, `ready`, or `unavailable` for this card only. The e2e wait also accepts the existing explicit Admin ModeEmpty as `empty`, but never interprets an absent marker on mounted Admin as success. It times out while pending. The walk checks before and after the DOM-quiet window in case a live ModeEmpty acquires the Admin live mark and mounts a pending card during that interval. It writes `adminEstop` per scan so its artifact distinguishes ready, unavailable, and empty; existing empty-surface and pending metadata remain. The demo walk still rejects ModeEmpty through its existing non-vacuity assertion.


Final verification on 2026-10-09: the rebuilt local FastAPI HUD passed all **6/6
Chromium tests** in this targeted spec (2.9 minutes). Four walks visited all 16
modes in live/demo at 1280×720 and 1440×900; the other two regressions verify
explicit empty versus missing/pending markers and the held response beyond the
old quiet window. There were no critical/serious axe violations in these walks;
axe's incomplete results remain reported, so this is not full accessibility
acceptance. Report: `/workspace/scratch/admin-estop-playwright-final.json` and
its log; per-mode JSON artifacts remain under `frontend/e2e/artifacts/`.

The independent gpt-6-sol/high review's legitimate live-empty finding was fixed
before the browser run. The helper now records ready/unavailable/empty, requires
the active Admin rail, and rechecks after DOM quiet to catch an empty-to-mounted
transition. A real Admin surface with no marker still fails. The demo walk's
existing non-vacuity assertion rejects an empty surface. Original pause/resume
mutation behavior is preserved; the only response-validation change is the
initial GET's invalid/empty result settling as visibly unavailable.

Focused component tests **8/8**, frontend/e2e TypeScript, final Vite build,
status/Hermes regressions **86/86**, generated status/Hermes freshness and
whitespace checks passed. The existing large bundle warning remains. The
frontend tracked total is **1,962**, derived from the independently executed
combined baseline **1,959** plus the three new component cases. The whole
frontend suite was not rerun for this ten-line component delta; the focused
cases and real-browser walks cover it. Backend **21,003** and mobile **284**
counts/evidence are inherited from unchanged source. Vitest's `list` command
was inspected but is not used as a test count: it does not fully expand these
parameterized tests.

Only H277's previously current modes3.tsx evidence pin was refreshed after
bounded source review: the edit is confined to EstopCard, with ChatMode/image
props unchanged. H277 remains partial; pre-existing stale H168/H273 pins remain
untouched. No native-device or live-model acceptance is claimed. The broader
per-mode readiness row remains open. This local candidate has not been pushed,
merged or deployed. Next action: compose it with the separate research unit
while preserving each rollback boundary.
