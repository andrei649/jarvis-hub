# HUD muted text contrast

Generated 2026-10-09 UTC. Goal: retire the low-contrast `--ink-3` token from HUD
text while preserving its decorative uses. Base/head at design:
`da7c8a222c2cd0cb658b192c967194bc9c88efa3`.
Branch: `codex/hud-muted-text-contrast-20261009`.

The existing painted contrast inventory reproduces the backlog finding in the
real browser. It compares two screenshots with identical layout: normal paint
and transparent text paint, recovering the actual background under each glyph.
This covers gradients that axe often leaves in its incomplete bucket.

Baseline measured with Chromium 151.0.7922.173 on Linux, obsidian/cyan, English,
1440×900, device pixel ratio 1, against the freshly built bundle served by the
local FastAPI backend. The measured area is the chrome only: top bar, ticker,
rail, center tabs and input bar. The lane produced 114 text runs: 47 measured,
3 unpainted and 64 excluded; 28 of 78 grouped decisions failed their contrast
threshold. Many affected labels measured about 2.87:1, below 4.5:1 for normal text.
Artifact: `/workspace/scratch/hud-contrast-base-painted.json`.

Implementation scope: CSS text foregrounds, text SVG fills, inline text and
text-facing shared colour props use the existing readable `--ink-2` foreground.
Decorative strokes, icon-only colours and backgrounds retain `--ink-3`; its
palette definitions are not globally brightened. Content, authority, actions,
layout, font sizes and backend/native APIs do not change. Root rebuilds the
committed HUD bundle after source verification.

One `gpt-6-sol`/high agent owns source and meaningful foreground/contrast
regressions; root owns integration, browser evidence, generated bundle and
ledgers. No nested delegation. The plan is stored at
`/workspace/scratch/hud-contrast-plan.md`. No push, merge or deployment.

Final verification on 2026-10-09 UTC:

- Full frontend suite: **1,867/1,867**, **210 files**, report
  `/workspace/scratch/hud-contrast-frontend-final.json`. This includes the two
  new foreground/contrast checks. After that whole-suite run, the system-map
  unknown-status fallback and voice-settings gear received the two final fixes;
  the covering mic-lease, reconciliation, contrast and system-map suites passed
  **20/20** on the final source, report
  `/workspace/scratch/hud-contrast-followup-final.json`. The existing mounted
  system-map regression was strengthened rather than adding another test.
- Frontend TypeScript and final Vite build passed. Generated `agents/web/v2`
  assets are included; no dependency or backend change. The large-chunk notice
  remains a build warning.
- The existing painted Chromium suite and all four accessibility mode walks
  passed: **7/7**, 2.9 minutes. The mode walk visited 16 distinct modes per lane,
  at 1280×720 and 1440×900, both live and demo. No critical/serious violations
  were reported. Axe still left contrast unresolved on 989/1,357 live nodes and
  1,386/1,801 demo nodes respectively; those are not contrast passes. Each lane
  also retained its existing surfaced incomplete `bypass` finding in Interop.
- Final painted chrome: **zero failing measured decisions**. The two calibration
  controls (deliberately dimmed and invisible text) still passed their tests.
  Source artifacts: `/workspace/scratch/hud-contrast-base-painted.json` and
  `/workspace/scratch/hud-contrast-final-painted.json`.

| Painted chrome inventory | Before | Final |
| --- | ---: | ---: |
| Text runs | 114 | 97 |
| Measured runs | 47 | 46 |
| Unpainted runs | 3 | 3 |
| Excluded runs | 64 | 48 |
| Grouped decisions | 78 | 61 |
| Decisions below their threshold | 28 | 0 |

The populations differ because live reports and ticker content change. All 27
previously failing text labels that can be matched by visible text now pass,
with a minimum of **6.869:1**. Two badges acquired a status class, which changes
exact ancestor-based identity without changing their labels. The remaining
original value `○ —` became `○ OFFLINE`, measured at **6.933:1**. This is a
bounded comparison, not a claim that every original text run was remeasured.
The enabled voice-settings gear was the last measured residual at 3.175:1:
removing its whole-button opacity retains readable closed/open foregrounds.

Static token math covers both looks and both opaque grounds: the inherited
`--ink-2` foreground yields **6.830–7.067:1** on the matching theme grounds. The
regression guards the low-contrast token's return into text while preserving the
explicit decorative inventory. System-map off/unknown/unmapped status text is
readable independently of its outline, and off opacity stays on the rectangle.
Manual screenshots inspected the obsidian rendering and a CSS-forced graphite
preview; they are not a complete theme/mode conformance matrix.

Independent `gpt-6-sol`/high source review and scoped follow-up review found no
remaining Critical/Important issue. A separate named review checked changed
Hermes evidence for H063, H145, H156, H206, H277, H380, H417, H445, H464, H518,
H595, H605, H660 and H666. Exactly 22 changed frontend/test pins were refreshed,
with statuses and remaining-work fields preserved. H156's Apply-button citation
now resolves to the actual control, and H145 describes DEBUG as muted/readable.
The already-stale H135 and every unrelated pin were left alone. Status/Hermes
Python tests passed **86/86**; count/freshness/diff checks passed. Backend and
mobile full-suite counts were reused without claiming new runs.

Limits: this fixes the reported ink3 text mechanism. It does not establish
complete WCAG conformance across every theme, opacity, accent, overlay, device,
state or non-text element. Unpainted, excluded and axe-incomplete entries are
not passes. Native colours use a separate theme and need separate evidence.
Rollback reverts this unit's source and generated bundle together.

This is a verified local candidate, unpushed and unmerged. Further accessibility
coverage, the independent native candidates and the wider project backlog remain
open. Next action: preserve this rollback unit and continue the remaining local
software work.
