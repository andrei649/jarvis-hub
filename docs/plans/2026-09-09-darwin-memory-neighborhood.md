# Truthful memory neighborhood

Generated 2026-09-09; final update 13:46 UTC. Goal: in live Memory mode, browse actual stored entities and
the selected entity's relationships instead of seeded graph nodes and demo dates.
Base/head before implementation: `652f6cf3a2f645be202f0ab7840ed69f4a498155`.
Branch `codex/darwin-memory-map`; worktree `.worktrees/darwin-memory-map`; lease none.

The recent Darwin discussion described feature comparisons, so this slice absorbs
the useful memory-navigation idea directly into Nerva. It does not install Darwin,
call a Darwin service, add a 3D renderer, claim semantic distances, implement study
restrictions, or introduce CAD/house changes. No new backend or write endpoints.

Design: keep existing memory statistics, use the current authenticated KG list
and detail reads, expose a bounded selectable neighborhood and a readable list,
and make empty/unavailable/loading states explicit. Abort obsolete requests and
ignore late responses. Only explicit Demo mode may show the old sample graph,
sample recalls and historical slider. The live view groups selectable entity names
and relation rows; it assigns no spatial positions or historical state.

Likely paths: frontend Memory mode and app demo prop; a small API adapter and
neighborhood component; focused tests; BACKLOG and HUD/mobile parity. Reuse the
one-attempt authenticated transport arriving in the Images PR; do not edit that
pending branch or duplicate its helper. Source/test work can proceed now; bundle,
full tests and generated status wait until root confirms Images has merged.

Tests: first reproduce live-mode sample node/date leakage, then real list/detail
selection, empty/error truth, strict response bounds, auth, cancellation and late
selection races; explicit demo stays separate. Focused tests during development;
full frontend suite, typecheck and production build on the final integrated base.
Independent review is assigned after the source stabilizes.

Rollback: revert this single frontend read-only slice and its parity updates.
Dependencies: existing KG APIs and the pending Images transport helper.

Checkpoint 2026-09-09: the initial regression failed on live sample nodes and demo
isolation, then implementation passed 18 component/boundary checks. Review identified
the recall route's HTTP-200 error envelope; three regressions reproduced the false
empty state, and refused/malformed responses now show the sanitized unavailable state.
API validation,
auth, deadline and body-cancellation tests are written and await the helper's merged
base. Independent source review requested from scope_review. Native Memory already
has entity list/detail, so H18.28 tracks only connected-neighbor navigation and
bounded cancellable reads. Next: integrate the fresh base after root notification,
run the final suite/typecheck/build and review, then commit a clean handoff. No push
or merge from this task.

Integrated checkpoint 2026-09-09: root explicitly handed off HUD dependency base
`b806d87b0903907aa19dab38ee91e9d7a6d6d545`; the memory-only source commit rebased
cleanly to `b8af4f34335960957c912a91851847966c5b5234`. Preserve the b806 boundary:
root will later rebase only this memory slice onto the final merged HUD base.
Source review is clean, with 43 focused tests and typecheck independently repeated.
The full frontend suite passed all 1,127 tests using Node 24.17.0, Vitest 5.0.0,
Vite 8.2.2 and TypeScript 7.0.2 from the existing isolated exact-lock runtime.
The JSON report is outside tracked source at
`C:/Users/andrei649/AppData/Local/Temp/nerva-darwin-memory-map-vitest.json`.
Production build generated `index-QYCwpAfv.js` (SHA-256
`540273053aa060380c14057225a1b33b0c9462cc0fc098f842a3a78d5f8bf048`).
All 56 Python HUD-parity, documentation-reference and status-sync checks passed;
generated status and measured frontend count verification are in sync. Backend and
mobile counts are reused unchanged from the dependency base. Independent Chromium
149.0.7827.55 smoke passed: Alpha/Beta/Gamma selection, relationships, empty/auth/
unavailable states, live/demo separation and JS/CSS refetch after hard reload. The
synthetic server received zero writes, and its preview was closed. Browser report:
`C:/Users/andrei649/AppData/Local/Temp/nerva-memory-neighborhood-browser-review/final/proof.json`.
No live owner-memory, Neo4j, PWA or Darwin service was exercised. Next action: hand
the clean memory-only commit to root for rebasing from the b806 dependency boundary
onto the merged HUD base; preserve this test JSON for count verification.
