# UX review — HUD v2 + WorldView (pre-manual-test, 2026-06-10)

> Deep UX pass before the owner's hardware manual-test run. Method: two static code
> reviews (HUD `frontend/src`, WorldView `worldview/frontend`) **plus** rendering the real
> HUD bundle in headless Chromium and looking at the screenshots. Triaged to what's worth
> acting on — most findings are P2/P3 polish; the design is genuinely solid and the honesty
> system works (verified visually). Companion to `docs/design/HUD_V2_REMAINING.md`.

## What the screenshots confirmed (verified, not just claimed)

- **Honesty system works.** Top bar shows `DATA OFFLINE` + `○ EMPTY` when disconnected, flips
  to amber `◐ DEMO` with the "seeded sample, not your live backend · exit demo" banner in demo.
  Trust Center's audit chain renders "chain verified · no tampering detected · Merkle-verified";
  the kill-switch honestly says "unavailable" in demo rather than faking it. The %-local meter
  renders cleanly (87% demo fallback). No panel passes seed off as real.
- **The design is polished** — on-brand void/cyan, legible, consistent. Most "confirm it works"
  review items demonstrably do.
- **The one verified high-impact gap → fixed in this pass:** the first-run cockpit (server up,
  no model, no plugins — the exact manual-test starting state) was a wall of "not connected"
  with **no next step**. Added `FirstRunBanner` (`app.tsx`): a dismissible, model-aware welcome
  strip ("No language model loaded yet — start LM Studio…" / "Connect plugins in Admin…") with a
  one-click "preview with demo". Shows only when `serverUp && !model && !demo`, remembered via
  `localStorage['hud.seen']`.

## HUD v2 — remaining findings (triaged, for owner to prioritize post-test)

**P1 (verify during manual test; fix if confirmed annoying):**
- **Double-submit during streaming** — chat input has no in-flight guard; pressing Enter again
  mid-stream can fire a second turn (worse with the voice loop). `cockpit.tsx` InputBar / `app.tsx:runTurn`.
- **Muted-mic affordance** — when `JARVIS_MIC_MUTED`, the mic button only dims (opacity .4); looks
  "inactive", not "forbidden". TopBar MIC badge is clear (`⊘ MUTED`); the input button should mirror it.
- **Admin-token prompt is one-shot** — `client.ts` prompts once per session; cancel/wrong-token →
  stuck until reload (`_prompted` never resets). Surface token entry in settings instead of `window.prompt`.

**P2 (rough edges):** kill-switch toggle failure has no error toast (silent revert); payment
approve/reject buttons lack a busy/disabled state (double-click risk); autonomy AUTO/ASK/OFF group
shows nothing while `mode===null` (looks all-off while loading); voice button clickable even when
STT capability is false (errors only after click); Console reload (↻) has no success feedback;
dossier "recent runs" hides on fetch failure (can't tell "empty" from "failed").

**P3 (polish):** inconsistent empty-state wording across panels; cognition trace renders
`undefined ms` when timing missing; no `prefers-reduced-motion` on the cognition stage animations;
modals don't trap focus / don't lock background scroll; "ALL NOMINAL" situation label shows even
when data is offline.

## WorldView — findings (code-reviewed only; not rendered here — needs the Node stack + API)

WorldView is **notably less polished than the HUD** on degradation/onboarding — expected for the
newer standalone stack. Its data layer and WebSocket resilience are sound; the gaps are UX-surface.

**P1:** API-down / empty-globe gives no explanation or recovery path (tiny red status dot only) —
a first-run user with no `:4000` API sees a dark globe and assumes it's broken
(`useWorldViewData.ts`, `DeckGlobe.tsx`); "connecting" state on load is near-invisible
(`StatsHud.tsx`); LIVE-vs-HISTORICAL mode is a dim toggle, easy to miss you've left live
(`TimelineScrubber.tsx`); no symbol/colour **legend** for the layers (aircraft/vessel/sat/jamming).

**P2:** keyboard shortcuts (space / L / ←→ / esc) are undiscoverable (no help overlay);
Mapbox-token-missing hint is tiny, low-contrast, map-mode-only; Stats + Export panels crowd the
same top-right corner; status-dot contrast fails WCAG (`text-white/30` on near-black).

**P3:** no graticule coordinate labels; provenance jargon ("valid time" / "transaction time")
unexplained; dark-vessel click shows generic props, not the alert context; no responsive layout
for <1280px (panels overlap); no WebGL-unavailable fallback/error boundary.

## Recommendation

Do **not** bulk-fix before the manual test — verify the P1s on real hardware first (several may be
non-issues in practice; the manual run is the cheapest way to confirm). The first-run banner is the
one fix that *helps* the test (the tester is the first-run user). Everything else is tracked here +
in `BACKLOG.md` TASK-4 for a focused post-test UX pass. WorldView's P1s (API-down explanation,
layer legend, LIVE/HISTORICAL clarity) are the highest-value items in either frontend and worth a
dedicated session.
