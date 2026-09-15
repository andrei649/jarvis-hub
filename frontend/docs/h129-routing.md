# H129 URL routing — design and execution plan

Goal: give every existing HUD mode and console panel a reloadable, shareable URL with browser history, titles and actual lazy chunks. Base: f3b20d3e1b97ffcb0ccde17c5e2b11f56034bd4c. Generated: 2026-09-15. Head: the commit containing this file (base above; exact SHA reported in the integration handoff). Paths: frontend/src routing, app, world_app, gap and regression tests. Next action: parent integration review and global evidence update.

Frozen source: capability 129 in docs/research/2026-09-07-hermes-absorption-ledger.json. Its functional contract is deep linking, lazy fallback, unknown-route handling, context remount and page titles; Hermes's exact 20 routes and plugin registry are not Nerva interfaces.

Verified design: browser History API with one shared URL snapshot subscription; no router dependency. Canonical /v2/<mode> includes jobs and world; /v2/console is the index and /v2/console/<explicit-stable-id> selects one panel. Rail, tabs, hotkeys, palette and desktop handoff call the same navigation function. Preserve unrelated query/hash state including demo and desktop. Legacy world query/hash is accepted at the root and removed when leaving it. Root defaults to cockpit (chat for floating); unknown paths replace to that default, showing an explanation. Titles derive from validated route metadata. Floating remains a chat-only surface and canonicalizes incompatible routes to chat.

Lazy imports replace all eager mode/gap imports from app. Existing module groups are chunk boundaries; console panel identifiers live in a metadata-only registry so URL validation never imports gap. First-run pure predicates move to a small module and remain re-exported for callers. Suspense provides a status fallback; failed chunks provide a reload action. The console index exposes ordinary links and selected panels have a focusable heading and a return link; switching selected panels unmounts prior panel state. Existing backend/profile models remain unchanged: there is no global profile selector or profile context to key on. Route content is keyed on route and demo context to prevent stale panel form state crossing that existing context boundary. Existing application conversation/preferences remain owned by App.

Non-goals: new backend routes, authority changes, dependencies, plugin registry, invented user profiles, global ledger/counter edits. Mobile: browser URLs work through the existing /v2 SPA fallback; no native mobile navigation changes. Rollback: revert this frontend commit. Dependencies: existing React/Vite/Vitest only.

Execution (inline, parent coordinates integration):
- [x] Add routing regression tests for all known modes, explicit panel metadata, initial/reloaded URL, push/pop, unknown paths, preserved query/hash, legacy world, floating and titles; observe failure before implementation.
- [x] Implement metadata registry and useHudRoute subscription/navigation; replace mode/console state at every existing entry point and route World.
- [x] Add console selection/focus regression and lazy chunk boundary verification; observe failure, then introduce lazy mode imports, lightweight onboarding helpers and selected console rendering with fallback.
- [x] Run relevant frontend regression tests with one worker, typecheck and production build; inspect emitted chunks. Report existing failures honestly. Include the production agents/web/v2 bundle; parent owns global evidence/counters.

Self-review: Nerva route coverage is mapped above; Hermes multi-profile switching remains absent and is not claimed equivalent. Plugin-aware redirection uses Nerva's finite registered surfaces; profile-keying uses only the existing demo context. No URL-derived action or mutation is introduced.


Delivered: 18 mode routes, console index, and 113 explicit panel URLs. World and console close restore the invoking mode; a directly loaded overlay defaults back to cockpit. Mobile HUD clipping prevents wide intrinsic desktop panels from moving fixed route controls outside the touch viewport. Navigation mounts only the selected console panel; business writes still require existing panel actions.

Verification (2026-09-15, Node v24.20.0, existing installed dependencies):
- Full frontend `node_modules/.bin/vitest run --maxWorkers=1 --reporter=json --outputFile=/tmp/h129-full.json`: **1208 passed, 0 failed, 150 test files**. Four legacy registration tests were updated from parsing the removed SECTIONS source text to checking actual route metadata. Existing jsdom prompt/navigation notices remain in that suite.
- Final focused routing, App, console, boundary and migrated registration suite: **58 passed** after the final context, fallback and World return-path changes.
- App and E2E TypeScript checks: `node_modules/.bin/tsc --noEmit` and `node_modules/.bin/tsc --noEmit -p tsconfig.e2e.json` passed.
- Production Chromium smoke: `node_modules/.bin/playwright test --config playwright.routing.config.ts`: **2 passed**, desktop 1440×900 and Pixel 7. It exercises actual bundle lazy loading, console links, selected-panel focus, real reload, Back/Forward, unknown URLs and no business mutations. All non-bundle requests are stubbed locally; this is not live backend evidence. Desktop/mobile screenshots were inspected.
- `node_modules/.bin/vite build` produces separate mode, World, jobs and gap chunks. The manifest inspected in an auxiliary /tmp build confirms the entry statically imports only the shared API client; route chunks are dynamic. A repeated production build was verified by SHA-256 file inventory: all 16 output files were identical.

The browser spec also runs with the repository E2E base URL, but its isolated config avoids booting or mutating a backend. Native mobile parity is unchanged; the browser surface is tested at mobile dimensions. There is no plugin route registry or global user-profile switch in this application, so neither is fabricated by this change. No global ledger/completion status is changed here.


Review follow-up: overlay return destinations now belong to each browser history entry, not a mutable component ref. Returning to an older World or Console entry restores that visit's invoking page, including after a reload. Panel navigation preserves the console origin; nested overlays snapshot and restore the parent return chain. Unrelated history state and the current demo/query/hash context are preserved. A direct bookmark without return metadata closes to cockpit. Seven additional regression cases cover historical World/Console visits, both remounts, both direct bookmarks, and nested overlay navigation.

Follow-up verification: 52 focused routing/demo/desktop tests passed, both TypeScript checks passed, desktop and Pixel 7 browser smoke passed (2/2), and all 16 production files matched a second build by SHA-256. The prior full-suite result above predates the seven added regressions; it is not presented as a full rerun of this follow-up.
