# H29 Media Director Completion Design

**Date:** 2026-07-13  
**Owner decision:** complete H29 autonomously, including H29.3, H29.6, HUD, and mobile parity.

## Goal

Finish the Media Director as an honest, default-off presentation fabric: generated catalog
items and governed web URLs resolve into concrete content, interrupt and duration semantics are
enforced instead of documented only, the three wave-2 modules graduate from the park policy,
and browser/mobile users can inspect and control the same governed API.

## Non-goals

- No credentials, vendor accounts, NAS mounts, Chromecast hardware, Spotify tokens, or cloud
  generation are silently configured by the repository.
- No direct device or browser calls outside `CapabilityActionAPI` and the existing governed
  driver seams.
- No arbitrary local paths, permissive URL fetching, prompt-history recording without opt-in,
  or mobile/browser bypass around approval results.
- No changes to `training/` or `rust/`.

## Architecture

### 1. Resolver chain

`MediaDirector` receives a bounded resolver chain rather than treating `catalog` and `query`
as driver-owned opaque strings.

1. `local` resolves only existing regular files under configured roots.
2. `catalog` loads a real `MediaCatalog` item by id, then revalidates its path or URL through
   the same local/URL resolver used for direct input.
3. `query` searches the real catalog and succeeds only for one unambiguous result; zero or
   multiple matches produce stable refusal reasons and bounded candidate metadata.
4. `url` is checked by a `GovernedBrowser`/`BrowserPolicy` navigation preview with an
   owner-configured allowlist and the existing SSRF guard. Resolution does not fetch or open a
   browser; the target driver remains the only actuator.

The catalog remains opt-in through `JARVIS_MEDIA_CATALOG`. URL egress remains fail-closed when
no allowlist is configured. Resolved content carries provenance (`direct`, `catalog`, or
`catalog_query`) without exposing catalog prompts or filesystem roots in errors.

### 2. Honest session semantics

An active session interrupted with `urgency=high` consumes the existing shared
`InterruptBudget`; exhaustion refuses before driver actuation. Starting playback on an idle
target does not consume attention budget.

`duration_seconds` may not be silently ignored. A driver must explicitly advertise and accept
bounded duration scheduling, or the director returns `duration_unsupported` before actuation.
Status verification includes the driver-reported duration contract where supplied. This keeps
the default `NullMediaDriver` honest and avoids an out-of-kernel background timer.

### 3. Controlled wave-2 graduation

`image_gen`, `media_gen`, and `media_skill` keep their current local-first and injected-host
boundaries. Graduation adds hermetic reality cases proving:

- disabled or missing host backends never claim success;
- local generation can be cataloged and resolved for presentation;
- paid/cloud generation remains durable-approval gated;
- media summarization cannot download until an explicit governed host seam is provided;
- no network, device, or generation action occurs from a null/default constructor.

After these cases pass, only the three wave-2 entries are removed from `PARK_POLICY`. Wave 3,
`training`, `rust`, and park-policy self-protection remain unchanged.

### 4. Browser HUD

Add a Media Director Console panel over the existing `/api/media/*` routes. It shows:

- default-off/degraded status;
- registered devices and current sessions;
- a bounded present form for catalog id/query, governed URL, or local reference;
- restore controls and honest nested action status (`output.ok`), never treating outer
  `completed` as proof of playback.

Admin device registration/removal remains clearly separated from user-level present/restore.
The panel does not embed remote media or leak local paths.

### 5. Mobile parity

Add a native Media surface backed by the same API contract. It provides device/session reads,
present/restore, and owner-only device registry controls when an admin token is configured.
The UI renders disabled, approval-needed, queued, denied, unverified, and verified states
distinctly. No autoplay, remote thumbnail fetch, or background polling is introduced.

## Safety invariants

- Media Director, catalog recording, host drivers, and generation backends remain default-off.
- Every presentation and restore crosses the Action Kernel at execution time.
- Resolver validation happens again at execution time; catalog content is not trusted because
  it was previously recorded.
- URL resolution uses the browser allowlist plus SSRF checks, including redirects at the real
  Playwright driver boundary.
- All collections, query text, URL/path strings, responses, and error details are bounded.
- Kill-switch, approval, and kernel denials never reach a driver.
- UI success requires both facade completion and a truthful nested domain result.

## Files and collision strategy

Primary files: `agents/core/media_director.py`, `agents/core/media_catalog.py`,
`agents/core/routers/media_director.py`, media/operator reality harness files,
`scripts/park_guard.py`, focused tests, `frontend/src/gap.tsx`, frontend tests,
`mobile/src/api/client.ts`, a native Media screen and tests, parity/type snapshots, and shared
truth files at final integration only.

H28 lands first because this work consumes its governed-browser graduation. `BACKLOG.md`,
`STATUS.md`, `project-status.json`, and other generated truth files are deferred to the final
H29 commit so parallel Claude work has one narrow reconciliation point.

## Verification

- Focused resolver, catalog, Media Director, route, Action Kernel, reality, and park-guard tests.
- Route/OpenAPI/auth/HUD parity snapshots and generated TypeScript gate.
- Frontend Vitest for reads, present, restore, nested failure, disabled state, and admin controls.
- Mobile Jest plus `tsc --noEmit` for API normalization and Media UI states.
- Ruff, Bandit on touched production Python, `git diff --check`, status-sync check, then full
  repository tests before merge.

## Rollback

Revert the H29 PR. Default-off flags and `NullMediaDriver` mean no device state is created by
installing the code. Device/session/catalog stores remain backward-readable; the resolver chain
can be removed without migrating existing records.
