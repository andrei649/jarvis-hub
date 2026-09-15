# H135 appearance preference synchronization

Goal: the owner's existing display choices survive browser cache loss and follow
that owner to another browser. Base: 022218f74734cb6c3a50052f47075375adeff5b7.
Generated: 2026-09-15. State: browser implementation verified; subsequent font and native deliveries linked below.
Spec: frozen H135, docs/research/2026-09-07-hermes-absorption-ledger.json.

Architecture: one instance-wide appearance document in the existing Settings DB;
a narrow user-guarded GET/PUT /api/preferences/appearance; a shared React hook
performs boot hydration, immediate local changes and serialized explicit saves.
This is the existing single-owner instance, not a new per-account/profile model.
No admin API expansion, kernel change, credentials, custom CSS/assets/fonts,
translation work, arbitrary config writes or new dependencies.

Contract:
- Fixed fields: accent (cyan/amber/green/violet), look (obsidian/graphite), density
  (compact/normal/comfy), motion (system/calm/lively), scanline and dotgrid (on/off).
  system motion follows prefers-reduced-motion; only explicit calm/lively overrides it.
- GET is read-only and returns canonical preferences plus whether any owner choice
  was stored. Unknown stale values coerce to defaults; unknown field names are refused
  on PUT. PUT updates only explicitly supplied fields, atomically merges the stored
  document and returns the resulting canonical preferences. No client can choose a
  settings category/key or reach other configuration through this route.
- Cache-only existing choices remain the offline/first-use display until shared
  choices exist. Boot hydration never copies defaults or legacy cache to the server.
  Only explicit owner changes enter an immutable prefix-scoped edit journal. Failed saves stay local and
  visibly unsynced, survive reload, and retry on an explicit retry or online event.
- Serialize saves; an old GET or PUT response cannot replace newer local edits.
  Focus refresh picks up changes from another browser, merging around pending edits.
  Browser cache keys include the deployment prefix; migrate legacy root hud.* values
  as display fallback. Legacy hud.motion is deliberately reset to System: the old
  client persisted OS-derived defaults without provenance, so it cannot distinguish
  an explicit override. New explicit motion choices remain syncable.
- Each journal entry has its own key; cache refreshes cannot overwrite another tab's
  pending edits. Acknowledgement removes only the exact sent entries, even if the
  originating component unmounted. Web Locks serialize same-origin tabs where
  available. Server revision CAS protects ordinary LAN HTTP without Web Locks:
  _revision is bounded concurrency metadata, excluded from display fields; a stale
  transaction returns 409. The client rereads server revision and current journal,
  retries only remaining entries, and stops after eight conflicts with visible retry.
  Separate browsers use atomic partial merges; conflicting explicit same-field edits
  converge according to successful server writes, not a client-clock authority.
- Cache/storage unavailable: choices still work in memory but cannot survive browser
  closure. Appearance changes are cosmetic and do not enable arbitrary config writes.
- Prefix-aware transport uses the existing client and preserves auth handling.

- [x] Backend: add core/appearance.py, routers/preferences.py and one Settings DB
  default document; wire router. RED then GREEN tests/test_appearance_preferences.py:
  empty defaults, persistence/new client, atomic partial merge, stale value coercion,
  body bounds/unknown fields, guard denial, unrelated settings unchanged, DB failure.
- [x] Frontend: add appearance.ts with pure bounded normalization and useAppearance;
  integrate App/Palette setters and a concise unsynced status/retry control. RED then
  GREEN appearance-sync.test.tsx: boot no writes, two browsers/cache recovery, stale
  hydration/save, failed save/reload/retry, OS motion, prefix cache and URL, unmount.
- [x] Browser: isolated real app/DB plus two storage contexts; change via palette,
  fresh browser restores it, offline change/reconnect converges, prefix works.
  No providers, production writes or native-authority changes.
- [x] Finish: affected backend/frontend tests, full frontend (one worker), both
  typechecks, deterministic production bundle, relevant route/parity checks.
  Commit only scoped source/tests/module guide and generated agents/web/v2 output.

Rollback: revert this coherent feature and bundle; the inert appearance Settings DB
row can remain without affecting older clients. Root integrator owns all global
backlog/Hermes/status/count changes, publishing and merge.

## Verified scope and subsequent H135 deliveries

This increment covers the browser HUD, ambient presentation and responsive phone
layout through the shared App appearance hook. This original increment did not
include native consumers or font overrides. Subsequent [local font preferences](h135-font-preferences.md)
and the [native appearance consumer](../../mobile/docs/h135-native-appearance.md)
complete the accepted cross-client persistence contract. Native reads the same
server document on boot and foreground entry, with a connection-scoped cache
and documented platform font fallbacks. Existing native desktop origin and
route authority remain unchanged; H130 browser prefix hosting boundaries apply.

Final evidence: 13 new API tests; 105 affected backend tests passed. All 1,247
frontend tests passed (18 new), plus six appearance, two routing and 16 base-path/PWA
real isolated-browser checks (desktop and Pixel 7). Both TypeScript programs and
the existing native route manifest sync check passed. Two production builds matched
by SHA-256 across all 16 files. The scoped Graft graph was explicitly rebuilt and
checked fresh; no deep context index, hooks or dependency indexing were enabled. Browser checks exercise
real user-guarded GET/PUT over the temporary Settings DB, root and /one paths,
fresh storage/cache clearing, reduced motion, offline convergence, and two offline
tabs closing/recovering without Web Locks. No native GUI or provider proof is claimed.
