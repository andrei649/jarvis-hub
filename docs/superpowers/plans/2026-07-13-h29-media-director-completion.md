# H29 Media Director Completion Implementation Plan

> Execute with `superpowers:subagent-driven-development`, strict TDD, and fresh review after
> every task. H28 must merge before implementation rebases and starts.

**Goal:** Complete H29.3/H29.6 plus browser HUD and native mobile parity, while closing the
duration and K3 interrupt gaps found in the completion audit.

**PR declarations:**

```text
unpark: wave-2
unpark: park-policy
```

## Task 1 — Real catalog and governed-browser resolver chain

**Files:** `agents/core/media_director.py`, `agents/core/media_catalog.py`,
`agents/core/routers/media_director.py`, `tests/test_media_director.py`,
`tests/test_media_catalog.py`, `tests/test_media_director_routes.py`.

- [ ] Add failing tests for catalog id, unique query, missing/ambiguous query, nonexistent local
  files, catalog path revalidation, empty URL allowlist, disallowed/private URL, and allowed URL.
- [ ] Implement injectable bounded resolvers that use the real `MediaCatalog` and
  `GovernedBrowser.preview`/`BrowserPolicy`, never fetch during resolution.
- [ ] Bind catalog, media roots, and URL allowlist from explicit owner environment settings in
  the route-owned director factory; malformed settings fail closed.
- [ ] Prove every resolved reference carries bounded provenance and every refusal occurs before
  driver invocation.
- [ ] Run focused tests, Ruff, Bandit, and commit the slice.

## Task 2 — Enforced duration and K3 interrupt semantics

**Files:** `agents/core/media_director.py`, `agents/core/routers/media_director.py`,
`tests/test_media_director.py`, `tests/test_media_director_routes.py`, relevant K3 tests.

- [ ] Add failing tests proving active high-urgency interruption consumes the shared K3
  `InterruptBudget`, exhaustion refuses, idle playback consumes nothing, and low/normal urgency
  still observes etiquette.
- [ ] Add failing tests proving `duration_seconds` is either explicitly supported and verified by
  the driver or refused before actuation; it is never ignored.
- [ ] Inject the live orchestrator budget at request time without weakening the action facade.
- [ ] Run media/K3/action-auth tests, Ruff, Bandit, and commit the slice.

## Task 3 — Controlled wave-2 graduation and reality pack

**Files:** `agents/core/image_gen.py`, `agents/core/media_gen.py`,
`agents/core/media_skill.py`, `agents/core/observability/reality_harness.py`,
`tests/test_h29_media_reality.py`, `scripts/park_guard.py`, `tests/test_park_guard.py`, adjacent
media tests.

- [ ] Add red reality tests for null/default refusal, local generation→catalog→presentation,
  cloud approval gating, summarizer host-boundary refusal, and zero ungoverned actions.
- [ ] Make the minimum bounded/default-off module hardening required by those tests; do not wire
  ambient host tools or credentials.
- [ ] Add all H29 cases to the canonical harness and prove kernel halt/denial reaches no driver.
- [ ] Remove only `image_gen`, `media_gen`, and `media_skill` from `PARK_POLICY`; update guard
  tests so wave 3, owner-only modules, and self-protection remain locked.
- [ ] Run reality, media, park-guard, release-gate, Ruff, Bandit, and commit.

## Task 4 — Media Director browser HUD

**Files:** `frontend/src/gap.tsx`, focused `frontend/src/test/*`, styles if required,
`docs/design/HUD_V2_REMAINING.md`, HUD parity classifications.

- [ ] Add failing Vitest coverage for device/session reads, disabled state, bounded present form,
  approval/queued/denied states, nested `output.ok=false`, verified success, restore, and admin
  device controls.
- [ ] Implement the Console Media Director panel with clear read/user/admin zones and no remote
  media embedding.
- [ ] Remove the Media Director punch-list entry and reclassify the existing endpoints as live in
  HUD parity.
- [ ] Run focused Vitest, full frontend tests/typecheck, and commit.

## Task 5 — Native mobile parity

**Files:** `mobile/src/api/client.ts`, `mobile/src/screens/MediaScreen.tsx`, `mobile/App.tsx`,
mobile API/UI tests, `mobile/PARITY.md`, `mobile/README.md`.

- [ ] Add red Jest tests for safe response normalization, disabled/error states, reads,
  present/restore, nested result honesty, and admin-token device registry controls.
- [ ] Add the native Media tab/surface over the unchanged API with explicit user actions only.
- [ ] Mark H18 Media Director parity complete and resolve the duplicate H18.21 identifier in the
  shared backlog during final integration.
- [ ] Run mobile Jest and `tsc --noEmit`; commit.

## Task 6 — Route/type parity, truth sync, and completion review

**Files:** route/OpenAPI/auth snapshots, `frontend/src/api/schema.gen.ts`, `BACKLOG.md`,
`STATUS.md`, `project-status.json`, and generated status docs only after all feature tests pass.

- [ ] Rebase on the merged H28/main state and resolve only intentional drift.
- [ ] Reseed route/OpenAPI/auth snapshots if the API contract changed and regenerate TS types.
- [ ] Mark H29.3/H29.6 and the Media HUD/mobile parity item complete with exact evidence; do not
  claim real hardware support beyond exercised host seams.
- [ ] Run the complete H29 suite, action/kernel/reality/parity gates, full frontend/mobile tests,
  full Python suite, code-health checks for touched files, and status-sync check.
- [ ] Request fresh spec and code-quality review; fix every Critical/Important finding with TDD.
- [ ] Commit truth sync, push a draft PR, monitor CI, then merge only after all gates are green.
