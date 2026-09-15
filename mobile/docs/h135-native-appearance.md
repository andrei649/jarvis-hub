# H135 Native Appearance Implementation Plan

**Goal:** Read the owner's server appearance on native clients without writes to the server.
**Base:** e71b7f3aa8eeb5e56543a9c6330875b6b9a68600. **Generated:** 2026-09-15. **State:** implemented and locally verified. **Next action:** independent review and parent integration.
**Spec:** frozen H135 in docs/research/2026-09-07-hermes-absorption-ledger.json; approved bounded native plan. Execute inline with planning/TDD and independent review; no delegation or publishing.

## Contract

GET /api/preferences/appearance after connection hydration and on foreground entry. Use the configured endpoint including its prefix, user header only, timeout and caller abort. No PUT, periodic polling, native font download, new animation or browser texture/density mapping. Unknown choices coerce to defaults. Native consumes accent/look/font; browser motion/scanline/dotgrid/density remain browser fields. Preserve OS accessibility settings and native motion behavior.

Persist a single versioned connection-plus-normalized-appearance record using existing AsyncStorage. Load legacy flat config. Serialize writes through one owner; delayed cache writes cannot overwrite newer credentials. Cache only fixed whitelisted fields. Every result/cache commit belongs to the connection epoch. Endpoint/user/admin credential changes clear effective preferences on the first render, not just in an effect. Unauthorized responses clear cache; offline failures may reuse only the current connection's cache. No tokens/hashes in cache keys or appearance status.

All 19 consumers become reactive using context and style factories, retaining component state. Text/TextInput wrappers apply body fonts; code stays independently monospace. Font IDs: theme/system-sans/system-serif/system-mono/jetbrains-mono. Native theme uses platform default; unavailable JetBrains explicitly falls back to platform mono. Colors map cyan/amber/green/violet and obsidian/graphite into native palette roles.

## Owned paths and TDD tasks

- [x] Storage/provider RED then GREEN: mobile/src/storage/settings.ts, context/ServerContext.tsx, new context/AppearanceContext.tsx, api/appearance.ts and appearance.ts. Actual React render tests and deferred AsyncStorage/fetch verify hydration, foreground/offline, timeout/unmount, unauthorized clearing and first-render connection isolation; serialized persistence must never restore old config.
- [x] Consumer RED then GREEN: mobile/src/theme.ts, new themed text wrappers, App.tsx, all 14 screens, AgentPicker/MessageBubble/SessionsModal and Markdown. Use memoized style factories/hooks; helper colors receive current theme. Runtime tests exercise all19 consumers, nested styles, code monospace and retained state across theme updates.
- [x] Reproducible harness: frontend/vitest.config.ts, frontend/vitest.native.config.ts and frontend/native-tests/*.test.tsx, native host/service mocks in frontend/native-tests/support. The default frontend npm test command runs both HUD and native projects; mobile/node_modules is not needed by this host harness. Reuse installed frontend React19.2.8/ReactDOM/Vitest/JSDOM; no renderer package. Host mocks do not constitute native GUI proof.
- [x] Restore mobile with existing lockfile npm ci; run native TypeScript and Jest, native render tests, relevant frontend typecheck and whole Ruff where applicable. No dependency version changes, global evidence or shipped browser bundle.

## Verification and rollback

Run one heavy process at a time. Record RED failures and exact GREEN counts here. Parent handles global metadata and integration; fonts source is root-owned. One coherent commit/revert unit covers native source, tests, harness and guide. Device font rendering and native GUI remain separately unverified unless an actual device/simulator run succeeds.

## Operational behavior and limits

The cache is one record containing the existing connection fields and only three normalized enum values, not a growing per-server catalog. Endpoint (including prefix), user-token and admin-token changes clear appearance together with the new configuration. The same existing AsyncStorage key is reused; no credential-derived identifier or hash is created. Writes are serialized and read the current owner record at execution time; this does not promise atomicity across keys or processes. Storage failures retain fetched preferences in memory with `uncached` status. Unauthorized responses clear memory immediately and attempt to persist that clearing; unavailable storage cannot guarantee durable clearing across process restarts.

Settings shows synchronization state and the read-only browser editing route. Theme/system-sans use the native default font; system-serif uses Georgia on iOS and serif on Android; mono and unavailable JetBrains use Menlo on iOS and monospace on Android. Settings explicitly explains the JetBrains fallback. All code text uses independent platform mono. Native consumers intentionally ignore browser scanlines, dotgrid, density and motion; no animation or accessibility setting is introduced or overridden.

## Verification evidence

Provider creation began with a missing-provider RED test. All 20 initial consumer tests failed with the original static palette; after conversion they passed. The Settings fallback test then failed before the explanation/status was added. Expanded runtime checks cover every render after URL/user/admin identity changes, delayed hydration and serialized persistence, stale response-body suppression, foreground refresh, 401 clearing, offline restart, storage failure, cancellation/unmount and a 15-second timeout.

- Native host suite: 38 tests across three files (12 provider cases, 21 consumer cases, four transport/font test declarations producing five cases).
- Existing native Jest: 137 tests, 32 suites, unchanged test count.
- Frontend app and E2E/config TypeScript: passed.
- Native TypeScript at this base: four pre-existing diagnostics only (expo-audio inherited addListener and callback parameter, plus two FlatList null empty components). The parent owns the separate dependency-layout/FlatList compatibility repair; this source unit does not alter those files' compatibility tokens or package dependencies.
- Device/simulator GUI, native font rasterization and OS background execution are not claimed by ReactDOM host tests. No server requests, provider spend, native preference PUTs or shipped web asset changes were made.

The default CI-compatible command, `cd frontend && npm test -- --reporter=json --outputFile=/tmp/nerva-native-default-suite.json`, passed **1,306/1,306** tests: the existing **1,268** HUD tests plus **38** native tests. This run physically moved `mobile/node_modules` outside the worktree for the entire command, proving the harness uses only frontend dependencies; the directory was restored afterward. The native and HUD test projects share the one-worker default. Both new test configurations are included in the existing E2E/config typecheck.

Independent review found and reproduced one startup corner: explicitly saving the empty default connection while hydration was delayed did not advance the epoch, allowing old saved credentials to reappear. The new regression failed against the reviewed source (12 pass / 1 fail). Every explicit settings save now advances the epoch, while an unchanged connection retains its existing appearance cache. This invalidates delayed hydration even for an empty save.

Corrected focused native suite: **39/39** passed (13 provider, 21 consumer, five transport/font cases). The earlier default combined run remains recorded above as 1,306; this additional regression makes the collected combined count 1,307, pending the parent integration gate.
