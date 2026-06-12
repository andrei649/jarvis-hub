# WorldView UX Redesign — Handoff to Claude Code

> Implementation package for **TASK-4** (BACKLOG.md, 🎨 P2, 13 SP). Input brief:
> [`WORLDVIEW_UX_BRIEF.md`](WORLDVIEW_UX_BRIEF.md) v1.1. Everything below is
> design-approved by the owner (mock verified 2026-06-12, all scenarios pass).
> Delivered by Claude Design 2026-06-12; landed in-repo with the **repo reality
> check** below (PR #193 shipped tactical fixes while the design session ran).
>
> **✅ IMPLEMENTED 2026-06-12 (PR #194):** all 11 steps of spec §6 are live in
> `worldview/frontend/` (140 frontend tests, tsc + build green). This document
> remains as the design record; the mock stays the visual reference for review.

## What's in this package

| Path | What |
|---|---|
| [`WORLDVIEW_UX_SPEC.md`](WORLDVIEW_UX_SPEC.md) | **★ The deliverable.** Tokens (→ `tailwind.config.ts`), zone system, the four P1 surfaces with exact copy, per-panel specs, negative-space grammar (§5.0), arrival moment (§5.1), demo lens (§5.2), a11y, and the 11-step per-panel PR order (§6). Build from this. |
| [`WORLDVIEW_UX_BRIEF.md`](WORLDVIEW_UX_BRIEF.md) | The v1.1 brief this design answers (context, ranked problems, constraints). The package's copy was byte-identical, so the repo file is the single source. |
| [`worldview-mock/index.html`](worldview-mock/index.html) | **Hi-fi reference mock** — open in a browser (needs internet for the React/fonts CDN). The Tweaks panel (bottom-right) switches all 7 scenario states: `live · demo · historical · replay · offline · firstrun · arrival`, plus the demo-lens toggle and inspector/help. This is the visual ground truth — match it. |
| [`worldview-mock/wvr-style.css`](worldview-mock/wvr-style.css) | Every token + component style, organized by panel. Token block at top maps 1:1 to spec §1. |
| [`worldview-mock/wvr-data.jsx`](worldview-mock/wvr-data.jsx) | The Hormuz demo scenario data shapes (mirror of the repo's seed). |
| [`worldview-mock/wvr-map.jsx`](worldview-mock/wvr-map.jsx) | `MapCanvas` (2.5D) + `GlobeCanvas` (3D) — SVG stand-ins for deck.gl. **The marker `Mark` component encodes spec §1.2** (shape+color redundancy); port these shapes to `deckLayers.ts` `getIcon`. Includes the negative-space elements: signal-loss ghost, DR cone, voided airspace. |
| [`worldview-mock/wvr-panels.jsx`](worldview-mock/wvr-panels.jsx) | All panels: AppBar, Legend+Layers (merged), Recon, Stats, Inspector, Alerts, Export, Timeline (event markers + replay window), FirstRun, Help, ArrivalBanner, DemoLens. |
| [`worldview-mock/wvr-app.jsx`](worldview-mock/wvr-app.jsx) | Zone composition + mode system wiring. |

## ⚠ Repo reality check (2026-06-12, post-PR #193)

While this design was produced, **PR #193** landed tactical fixes for the UX-review P1/P2s on
the *existing* UI. The spec still applies in full — it is the destination; #193 was triage —
but several steps are now **upgrades of shipped components instead of greenfield**:

| Spec item | #193 shipped (tactical) | Remaining delta (this spec) |
|---|---|---|
| §3.1 First-run overlay | `SystemStatus.tsx` — tone-coded API-down/connecting/empty overlay with recovery commands | Replace copy/layout per §3.1 exact copy; WebGL variant exists (`GlobeErrorBoundary.tsx`) — restyle |
| §3.2 Legend = layer panel | color swatches added to `LayerPanel.tsx` | Merge to one panel with **shape glyphs** (same SVG as map marks), counts, sub-encodings, trail/DR footer |
| §3.3 Mode system | amber "◷ HISTORICAL — press L" chip in timeline; LIVE button ring | Full system: 2px mode frame + app-bar mode pill + GO LIVE + DEMO watermark; one store value drives all three |
| §3.4 Right rail | Export collapsed to chip; Stats+Export stack in a right-rail column (overlap bug fixed) | Full zone system (app bar, left/right flex columns, kill `top-[19rem]`), Inspector into the rail |
| §4 Help overlay | `HelpOverlay.tsx` (`?` key + button) | Restyle to token system; shortcut grid incl. `1–5 · G · R` once those bindings ship |
| §4 Tooltips, timeline markers, Inspector humanization; §1 tokens/fonts; §1.2 shape encodings; §5.0 negative space; §5.1 arrival; §5.2 lens; demo badge | — (untouched) | Greenfield per spec |

Net: spec §6's order stands; steps 4, 5 and parts of 3 begin from #193's components rather than
from scratch. Read `worldview/frontend/components/{SystemStatus,HelpOverlay,GlobeErrorBoundary,
LayerPanel,StatsHud,TimelineScrubber}.tsx` before each step.

## Where it lands in the repo (`worldview/frontend/`)

| Mock | Repo target |
|---|---|
| token block (`wvr-style.css` top) | `tailwind.config.ts` + `app/globals.css` + `@fontsource/*` imports in `app/layout.tsx` |
| zone composition (`wvr-app.jsx`) | `app/page.tsx` — replace all absolute `top-[19rem]`-style offsets with the two flex columns |
| mode frame / pill / timeline restate | new `components/ModeFrame.tsx` + AppBar; state from `lib/store/useTimelineStore.ts` (one source) |
| AppBar | new `components/AppBar.tsx` (absorbs ViewToggle + CameraTour buttons) |
| Legend+Layers | rewrite `components/LayerPanel.tsx` |
| Stats / Export / Alerts / Inspector / Recon / Timeline | corresponding `components/*.tsx` per spec §3.4/§4 |
| FirstRun overlay | evolve `components/SystemStatus.tsx` per spec §3.1 (mount condition: no-API ∨ WS-closed>60s ∧ no cache) |
| marker shapes + negative-space grammar | `lib/deckLayers.ts` (IconLayer/getIcon per type; ghost/cone/void as separate layers) |
| tooltips | `lib/tooltip.ts` → styled HTML per spec §4 |
| arrival banner | parse `?from&to(&entity)` in `page.tsx`; new `components/ArrivalBanner.tsx` |
| demo lens | new `components/DemoLens.tsx`, tour-state gated |

## Ground rules (from the brief — non-negotiable)

1. **Honesty system**: never fake a healthy state; DEMO always badged (pill + watermark); scrubbing announces HISTORICAL; GO LIVE always one click.
2. **No targeting cosplay**: no reticles, lock-on, bounding-box acquisition. The lens is the only cinematic allowance, dismissable, reduced-motion-aware, never default.
3. **Red means wrong** — only dark vessels / alerts / offline. Military = amber hollow chevron. No marker uses accent cyan.
4. **A11y**: AA contrast, shape+text redundancy everywhere, focus-visible, focus-trapped overlays, `prefers-reduced-motion` on all loops.
5. **Implement per-panel** in spec §6 order (tokens → zones → mode system → …) — each step is independently shippable and reviewable.

## Verify against the mock

For each PR, open the mock at the matching scenario and compare. The owner's manual-test bar
(brief §10): first-run user understands the screen in ~10s with no backend; demo identifiable
from any screenshot; every mark decodable ≤1 click; mode readable from any corner; no overlap
at 1280×800; alert-triage ≤3 coherent surfaces.
