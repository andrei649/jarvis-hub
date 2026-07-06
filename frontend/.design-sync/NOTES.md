# design-sync notes — jarvis-hud-v2

- The frontend is a private Vite APP (no library build, no dist): converter runs in
  synth-entry mode from `src/`. Components live in flat top-level files
  (`primitives.tsx`, `gap.tsx` = many panels, `modes*.tsx`, `mesh.tsx`, `shell.tsx`).
- Styling: single `src/styles.css` (64KB) — full token system on `:root`/`.hud-root`
  (Obsidian/Graphite looks × 4 accents × density × motion via `data-*` attributes on
  `.hud-root`). Self-hosted variable fonts: Space Grotesk (`--font-ui`),
  JetBrains Mono (`--font-mono`) under `src/assets/fonts/`.
- Components expect a `.hud-root` wrapper for tokens/theme — previews likely need it
  (no React provider; it's a CSS class + data-attrs wrapper).
- Most `*Panel` components are live-dashboard panels that may fetch from the FastAPI
  backend (`/api/...`) on mount — expect loading/empty states in static previews;
  author with realistic props where the API allows, `overrides.skip` where they
  genuinely can't render statically.
- Backend contract: `src/api/schema.gen.ts` is typegen'd from the running backend's
  OpenAPI (`npm run typegen:openapi`).
- DesignSync auth was unavailable in the first sync session (non-interactive);
  build/verify ran local-first, upload deferred until the user authorizes
  (interactive `/design-login` or Claude Design "Send to Claude Code Web").

## Preview recipe (calibrated on the solo set, 2026-07-06)

- **Dark-first DS on a white card stage**: every authored preview wraps in
  `<div className="hud-root" style={{background:'var(--void,#04070e)', borderRadius:8, padding:16}}>`
  — without the void background everything washes out.
- `src/data.ts` is exported via `cfg.extraEntries` — previews use the repo's own
  seed data (`V2.TICKER`, `V2.AGENTS`, `V2.SEED_MESSAGES`, `V2.GLYPHS`,
  `V2.DOSSIER`, `V2.WEATHER`, …) for realistic content. `ICONS` is also a bundle
  export (icon path map for `Icon d={ICONS.x}`).
- `.d.ts` props are weak (`{x?: any}`) — always read the component's SOURCE file
  (flat: gap.tsx, shell.tsx, cockpit.tsx, modes*.tsx) for the real prop shape.
- Shell/ticker components take a `t` translations object — pass literal strings
  (e.g. `{situation:'SITUATION', allnominal:'ALL NOMINAL'}`).
- `Reactor`/icons draw in `currentColor` and size from their container — give
  the wrapper a color and explicit width/height spans.
- App-level exports excluded from sync: App, WorldAwareApp, WorldIntelligenceMode
  (componentSrcMap nulls) + src/main.tsx excluded from the synth entry
  (libOverrides fork — Vite bootstrap side effect).

## Wave-1 learnings (folded 2026-07-06)

- **Story-keyed fetch shim** — THE recipe for gap.tsx panels (zero props, self-fetch
  via useApi→window.fetch): each preview installs a module-scope fetch stub serving
  realistic JSON for that panel's exact endpoints, scenario keyed off the harness's
  own `?story=` param; unmatched paths pass through (offline cells need NO stubbing —
  the real 404 exercises the documented amber degrade row). Match full URL first
  (query strings!), then pathname. Safe: each card is its own page; capture waits
  networkidle.
- **Capture viewport (900×680) < the DS 1100px desktop breakpoint** (styles.css:581):
  `.col.scrollcol{display:none}`, rail labels stripped, clock shrinks. Fix via
  `cfg.overrides.<Name>.viewport = "1280x720"` (applied: ContextColumn, TopBar, Rail,
  Tabs). ContextColumn's preview also carries a harmless scoped re-assert of the base
  rule from the pre-override iteration.
- **Wide/tall shell strips**: use `zoom` on the wrapper (TopBar .72, Tabs .66, Rail .75),
  never squeeze widths (bars overlap). **Panel columns collapse to 0px outside the app
  grid** (`.panel-body{flex:1 1 0}`) — stage in a definite-height grid div.
- **position:fixed overlays** (Palette/Ambient/CinemaMesh/ConsoleOverlay scrims) are
  contained by a `position:relative; overflow:hidden; transform:translateZ(0)` stage.
- **Real-DOM-event staging** for prop-unreachable states (native value setter +
  `dispatchEvent(new Event('input',{bubbles:true}))`, `scrollLeft = scrollWidth`) —
  never lookalike markup.
- Seed gotchas: map `V2.DECISIONS` rows to add `_id`; pass `t={V2.I18N.en}` wholesale;
  CognitionStream needs app.tsx-style `state:'done'/'on'` mapped onto `buildTrace()`.
- Stage widths: 380 default; DecisionInbox/Missions ~440, MeshPeers ~460,
  DataSpaces ~480; ConsoleOverlay full-width 820×620 relative/hidden stage.
## Wave-2 learnings (folded 2026-07-06)

- **Second breakpoint at 1300px** (styles.css:493/544): `.auto-grid`/`.build-grid`/
  `.obs-grid`/`.admin-grid` collapse to one column and `.comms-body` narrows below
  1300px viewport WIDTH (media queries key on the viewport, zoom doesn't help).
  Fixed via `cfg.overrides.<Mode>.viewport = "1440x810"` for the 8 full modes +
  CommsMode + WorldIntelligencePanel. Some previews also carry a harmless
  ContextColumn-precedent scoped re-assert from pre-override iterations.
- **Roster correction**: WorldIntelligencePanel lives in `src/world-intelligence.tsx`
  (modes_world.tsx holds only the excluded app-level WorldIntelligenceMode).
- **Cross-origin fetch shim**: the Signal Layer client hits absolute
  `http://localhost:8787` URLs — pathname matching catches them; UNstubbed
  cross-origin paths fail with real network errors, which correctly drives the
  designed PARTIAL (Promise.allSettled) and layer-down states.
- Mode staging numbers: definite-size flex stages ~1240w, zoom .58–.66
  (ChatMode 880w @ .90); stage to content+~10%; `panel-body` clips silently —
  size stages by counting seed rows. Story-keyed shim also covers mode-internal
  loads (`/autonomy/mode` — no `/api` prefix).
- More product findings: AutonomyMode AUTO/ASK/OFF selection is a 0.3-opacity
  delta only (no `.pmode.on` rule); V2.COMMS seed threads lack `replyable`/
  `thread_id` (reply composer unreachable in demo); TodayPanel timestamp wraps
  (no nowrap); SafeCommsDraftPanel leaves its action select interactive under
  the offline degrade row; WorldIntelligencePanel shows green `freshness: ok`
  when the layer is fully down + renders "high high" (severity+confidence
  unlabelled); SandboxPanel has no <State> row (silent fail-open when offline).

## Known render warns (triaged legitimate — re-syncs: not new)

- **InputBar flagged `bad`/error by the render check**: the checker pattern-matches the
  MicError story's *intentional* on-screen copy ("mic permission denied — check browser
  settings"); `pageErrs` is empty, the sheet grades good. False positive by design of
  that story — do not "fix".
- 50+ informational `[RENDER_ERRORS]` warn lines are the fetch-shim panels' expected
  404s on unstubbed paths (the offline/degrade cells exercise them deliberately).
- `variantsIdentical` fires on ~38 components by construction: fetch-shim panels
  render the fallback scenario for ALL exports in the default grid view (no
  `?story=` param there) — the per-story captures differ and are what got graded.

- **Product findings for the DS team** (real component behavior, not preview bugs):
  DataSpacesPanel create-row clips "+ add" below ~460px incl. in the product's own
  320px console columns; DecisionInboxPanel shows green "all clear" copy even in
  error state; OraclePanel empty state double-renders its "nothing yet" line.
