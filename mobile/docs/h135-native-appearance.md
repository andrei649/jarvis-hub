# H135 Native Appearance Implementation Plan

**Goal:** Read the owner's server appearance on native clients without writes to the server.
**Base:** e71b7f3aa8eeb5e56543a9c6330875b6b9a68600. **Generated:** 2026-09-15. **State:** implemented and locally verified. **Next action:** independent review and parent integration.
**Updated 2026-11-23 (theme contract v1):** base `77d6db8861cc345ba6266bcf9ecdad39392e8fdc`, uncommitted on `claude/hud-redesign` (local only, nothing staged). Changed for native: `mobile/src/theme.ts`, `frontend/native-tests/transport.test.tsx`, `frontend/native-tests/consumers.test.tsx`, this file and `mobile/PARITY.md`. **Next action:** integration gate (full suites). See [Themes](#themes-2026-11-23-theme-contract-v1) for what changed; the sections after it are the original H135 record, with the stale colour lines corrected.
**Spec:** frozen H135 in docs/research/2026-09-07-hermes-absorption-ledger.json; approved bounded native plan. Execute inline with planning/TDD and independent review; no delegation or publishing.

## Themes (2026-11-23, theme contract v1)

The browser HUD now has nine looks, and native follows all of them through the existing `look` field:
seven **Nerva** themes, `ledger` (the default on both clients), `presence`, `briefing`, `workbench`,
`threshold`, `console` and `atlas`, plus the two **Classic** HUD v2 looks, `obsidian` and `graphite`.
`mobile/src/appearance.ts` accepts exactly the server's order of ids; anything else coerces to
`ledger`. The browser's new `scheme` field (`dark`, `light`, `system`) is a browser field: native
**follows the look but not the scheme** and always draws a theme's dark palette, Briefing's Night
included, although Briefing's browser default edition is Day. Native has no light palette, no theme
picker, and no per-theme typefaces, type scale, shapes or density; the owner changes the theme in the
browser (Settings → Personalisation, or the command palette) and native repaints on its next
foreground refresh.

**Palette source.** Each Nerva palette in `mobile/src/theme.ts` (`NERVA`) is the theme's dark block,
`:is(:root, .n-theme-scope)[data-look="<id>"]` in `frontend/src/theme/themes/<id>.css`, converted to
hex the way the browser paints it (CSS Color 4 OKLCH → sRGB, clipped, rounded). A `var(--n-…)` value
is followed to the role it names; a derived role the theme leaves unset takes its `tokens.css`
default. Native keeps its twelve roles, and because they are the HUD v2 roles they map the way the
browser's legacy bridge maps them (`frontend/src/theme/CONTRACT.md` §6):

| Native role | Theme role | Why |
|---|---|---|
| `bg`, `surface`, `surfaceAlt`, `border` | `--n-bg`, `--n-sheet`, `--n-sheet-2`, `--n-rule-2` | grounds and quiet edges |
| `text`, `textDim` | `--n-text`, `--n-text-2` | ink |
| `accent` | `--n-emph` | the bridge's `--accent`: emphasis, the current tab, links, names, Send |
| `accentDim` | `--n-rule-field` | the bridge's `--accent-dim`: an edge that identifies a control |
| `userBubble` | `--n-emph-wash` | the bridge's `--accent-faint`: the browser's user bubble, a chosen row |
| `ok`, `warn`, `danger` | `--n-ok`, `--n-warn`, `--n-bad` | status |

Every Nerva theme points `--n-emph` at its text ink, so native emphasis, links, tabs and filled
buttons are drawn in ink (the hard-coded dark label on a filled button still reads at 14:1 or more).
A theme's own accent colour (Ledger's vermilion, Presence's tungsten, Briefing's marker, the yellow
of Workbench and Threshold, Console's amber, Atlas's emerald) is reserved for what waits on the
owner; native has no role for that, so it does not appear in native at all. Until 2026-11-23 native
took `--n-accent` and `--n-accent-wash`, which spent Ledger's seal on every tab, link and button and
made a running task the same colour as a waiting one in Presence and Briefing. Classic is unchanged:
Obsidian or Graphite grounds with the owner's cyan, amber, green or violet accent.

**Status colours.** Each theme keeps its five status colours at least 0.05 apart in OKLab from each
other and from its text ink (contract §3), so native's `ok`, `warn` and `danger` now carry meaning in
every look. Before this update `warn` was the text ink in Workbench, Threshold and Console, `ok` was
the text ink in Briefing and the secondary ink in Presence; all five now have a colour of their own.
In Threshold, Console and Atlas `ok` is the theme's secondary ink by design (those themes draw
normal in ink, never green), so native `ok` equals `textDim` there.

**Drift guard.** `frontend/native-tests/transport.test.tsx` reads the Nerva theme list from
`frontend/src/theme/registry.ts`, parses each dark block, resolves references, and compares all
twelve roles of every Nerva palette exactly. When a theme file moves, it fails with one line per
role, `<look>.<role> is <native hex>, --n-<role> is <theme hex>`: paste the theme hex into
`mobile/src/theme.ts`. The same file checks that every palette value is a hex colour, that the
Classic accent axis leaves a Nerva palette untouched, that the seven grounds differ, that Ledger's
palette never contains its seal (`#fd6c48`), that native's default look is the browser's, and that
`ok`, `warn` and `danger` stay 0.05 apart from each other, from `text` and from `accent`.
`frontend/native-tests/consumers.test.tsx` mounts the app in Ledger (ground `#0e1210`, ink `#dde4db`,
no `#fd6c48` in any mounted style) and checks the repaint to Atlas on a foreground refresh.

**Verified 2026-11-23** (host ReactDOM tests, not a device): `npx vitest run --project
native-appearance native-tests/appearance.test.tsx native-tests/consumers.test.tsx
native-tests/transport.test.tsx` from `frontend/` passed 46/46 (14 provider, 23 consumer, 9
transport/palette/font). Before the palette was re-derived, the drift guard (still on the old
accent mapping) failed on presence and briefing `ok` and on workbench, threshold and console `warn`.
With Ledger's accent and userBubble and Workbench's warn deliberately set back to their old values,
the drift, palette and status tests failed with the
expected lines, and the consumer test failed on the vermilion in the agent chip, the push-to-talk
button and the active tab (values restored afterwards). `npx tsc --noEmit -p .` in `mobile/` exited
0. Native Jest was not run for this update (no native test reads a colour). No device, simulator,
native contrast or font rasterisation acceptance is claimed.

**Known gaps** (consumer files, not changed here): three native components draw `text` on an
`accentDim` fill (Memory's active segment, Compare agents' chosen agent, Sessions' continue button),
which is 3.9 to 5.2:1 across the Nerva looks and under 4.5:1 in Ledger, Briefing, Workbench and
Console; they should use `userBubble` as the chosen fill, as the browser's segmented control uses
`--n-emph-wash`. The briefing wall colours its "live" tone `ok` and its remaining tones `textDim`,
the same colour in Threshold, Console and Atlas; its state word still tells them apart.

## Contract

GET /api/preferences/appearance after connection hydration and on foreground entry. Use the configured endpoint including its prefix, user header only, timeout and caller abort. No PUT, periodic polling, native font download, new animation or browser texture/density mapping. Unknown choices coerce to defaults. Native consumes accent/look/font; browser motion/scanline/dotgrid/density, and since 2026-11-23 scheme, remain browser fields. Preserve OS accessibility settings and native motion behavior.

Persist a single versioned connection-plus-normalized-appearance record using existing AsyncStorage. Load legacy flat config. Serialize writes through one owner; delayed cache writes cannot overwrite newer credentials. Cache only fixed whitelisted fields. Every result/cache commit belongs to the connection epoch. Endpoint/user/admin credential changes clear effective preferences on the first render, not just in an effect. Unauthorized responses clear cache; offline failures may reuse only the current connection's cache. No tokens/hashes in cache keys or appearance status.

All 19 consumers become reactive using context and style factories, retaining component state. Text/TextInput wrappers apply body fonts; code stays independently monospace. Font IDs: theme/system-sans/system-serif/system-mono/jetbrains-mono. Native theme uses platform default; unavailable JetBrains explicitly falls back to platform mono. Colors: Classic maps cyan/amber/green/violet and obsidian/graphite into native palette roles; since 2026-11-23 each Nerva look has a fixed dark palette from its browser theme file (see Themes above).

## Owned paths and TDD tasks

- [x] Storage/provider RED then GREEN: mobile/src/storage/settings.ts, context/ServerContext.tsx, new context/AppearanceContext.tsx, api/appearance.ts and appearance.ts. Actual React render tests and deferred AsyncStorage/fetch verify hydration, foreground/offline, timeout/unmount, unauthorized clearing and first-render connection isolation; serialized persistence must never restore old config.
- [x] Consumer RED then GREEN: mobile/src/theme.ts, new themed text wrappers, App.tsx, all 14 screens, AgentPicker/MessageBubble/SessionsModal and Markdown. Use memoized style factories/hooks; helper colors receive current theme. Runtime tests exercise all19 consumers, nested styles, code monospace and retained state across theme updates.
- [x] Reproducible harness: frontend/vitest.config.ts, frontend/vitest.native.config.ts and frontend/native-tests/*.test.tsx, native host/service mocks in frontend/native-tests/support. The default frontend npm test command runs both HUD and native projects; mobile/node_modules is not needed by this host harness. Reuse installed frontend React19.2.8/ReactDOM/Vitest/JSDOM; no renderer package. Host mocks do not constitute native GUI proof.
- [x] Restore mobile with existing lockfile npm ci; run native TypeScript and Jest, native render tests, relevant frontend typecheck and whole Ruff where applicable. No dependency version changes, global evidence or shipped browser bundle.

## Verification and rollback

Run one heavy process at a time. Record RED failures and exact GREEN counts here. Parent handles global metadata and integration; fonts source is root-owned. One coherent commit/revert unit covers native source, tests, harness and guide. Device font rendering and native GUI remain separately unverified unless an actual device/simulator run succeeds.

## Operational behavior and limits

The cache is one record containing the existing connection fields and only three normalized enum values, not a growing per-server catalog. Endpoint (including prefix), user-token and admin-token changes clear appearance together with the new configuration. The same existing AsyncStorage key is reused; no credential-derived identifier or hash is created. Writes are serialized and read the current owner record at execution time; this does not promise atomicity across keys or processes. Storage failures retain fetched preferences in memory with `uncached` status. Unauthorized responses clear memory immediately and attempt to persist that clearing; unavailable storage cannot guarantee durable clearing across process restarts.

Settings shows synchronization state and the read-only browser editing route. Theme/system-sans use the native default font; system-serif uses Georgia on iOS and serif on Android; mono and unavailable JetBrains use Menlo on iOS and monospace on Android. Settings explicitly explains the JetBrains fallback. All code text uses independent platform mono. Native consumers intentionally ignore browser scanlines, dotgrid, density, motion and (since 2026-11-23) the colour scheme; no animation or accessibility setting is introduced or overridden.

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
