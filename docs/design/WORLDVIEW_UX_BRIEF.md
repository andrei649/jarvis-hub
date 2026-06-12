# WorldView — UX Design Brief & Handover (for Claude Design)

> A **self-contained** brief for designing a great UX for WorldView, the 4D OSINT globe.
> Written so a designer (Claude Design, Figma-driving Claude, or a human) who has **never seen
> this repo** can produce an implementable design. Everything needed is in this file: product
> context, the complete current-UI inventory (from code, with exact values), the data model the
> UI must communicate, the ranked problem list, brand + technical constraints, user journeys,
> success criteria, and the requested deliverables.
>
> Generated: 2026-06-12 · Owner: Andrei · Status: v1.1 (pre-manual-test) ·
> Sources: `worldview/frontend/` code read end-to-end, `docs/2026-06-10-ux-review-hud-worldview.md`,
> `worldview/docs/ROADMAP.md`, `docs/BRAND_BOOK.md` §7, `BACKLOG.md` H19 + TASK-4, `MOONSHOT.md` §5,
> `docs/research/2026-06-12-bilawal-worldview-reverse-engineering.md` (the benchmark, reverse-engineered).

---

## 0. The brief in one line

WorldView's engineering is done (33/33 backlog items, ~208 SP, full data path tested in CI) but its
UI is **"notably less polished than the HUD"** (UX review, 2026-06-10) — design the command-center
UX it deserves: **legible at a glance, honest about its state, on-brand (void/cyan cockpit), and
navigable by a first-time user without a manual.**

---

## 1. What WorldView is

**Product:** a *4D OSINT command center* — it fuses live and historical **air / sea / space /
cyber / context** signals onto a single time-scrubbable map/globe. One master clock drives every
layer; you can watch the world live or scrub back through 24 h of history and watch everything
move in lockstep. Inspired by Bilawal Sidhu's "God's Eye View" (the journalist/consumer OSINT
north star) and Palantir's patterns (ontology, provenance, governance — the enterprise ceiling).

**The five data layers:**

| Layer | id | What it shows | Source |
|---|---|---|---|
| Aerospace | `adsb` | Commercial + military aircraft, live positions | OpenSky / adsb.fi |
| Maritime | `ais` | Vessels; **dark-vessel detection** in geofenced choke points | AISStream |
| Space | `tle` | Satellites (optical/SAR) propagated via SGP4, + their **sensor footprints** | Celestrak / Space-Track |
| Cyber/EW | `ew` | GPS-jamming intensity on H3 hex cells | gpsjam.org |
| Context | `context` | Intel: dark-vessel events, geopolitical events, NOTAMs/zones | event/NOTAM feeds |

**The "so what" layer on top of the dots:** dark-vessel alerts, predicted **recon windows**
("a SAR satellite covers this AOI in 22 min"), event callouts, per-datum **provenance /
chain-of-custody** (source + bitemporal valid/transaction time), **cases** (multi-analyst
collaboration with a hash-chained audit trail), and **reproducible replay links / exports**
(GeoJSON, case briefs).

**Dual positioning** (matters for UX):
1. **Standalone product** — for OSINT researchers, journalists reconstructing events, maritime/
   commodity desks watching choke points, defense analysts. Self-hosted, like everything here.
2. **A JARVIS capability** — JARVIS (the local-first personal AI OS in this repo) operates
   WorldView in natural language via a dedicated agent (**Argus**) and MCP tools; its autonomy
   watcher surfaces dark-vessel/recon alerts into the user's daily digest (budgeted ≤4
   interrupts/day) with provenance links. UX implication: people will *arrive* in WorldView from
   an alert or a shared replay link (`?from&to`), not only from a cold start — landing into a
   specific entity/time must be a designed moment.

**Know the benchmark (and design our differences to be visible).** Sidhu's WorldView — the
direct inspiration — is reverse-engineered in
`docs/research/2026-06-12-bilawal-worldview-reverse-engineering.md`. In short: closed-source,
solo-built, aesthetic-first; Google **Photorealistic 3D Tiles** as the globe, custom GLSL "lens"
shaders (CRT scan lines, night-vision, FLIR thermal, military reticle), OSM traffic as particle
flow, CCTV projected onto 3D buildings; public launch ~April 2026; positioned as the demo for
"SpatialOS," a world model queryable by AI agents. He won on *cinema*; our durable differences
are **local-first + self-hosted + open source**, **governed** (provenance, audit, cases,
reproducible exports), and **operated by the user's own AI** (JARVIS/Argus) instead of a closed
cloud. The UX should make those differences *visible on screen* — provenance one click away,
honesty badges, replay links — not just claimed in marketing. His sousveillance line is
essentially our pitch: *"Same data streams… but the interface is in your browser, and you
control it."*

**Reference geography:** the default Area of Interest (AOI) is the **Strait of Hormuz**
(initial camera: lon 56.4, lat 26.6, zoom 6, pitch 30°). The demo seed is a full Hormuz scenario:
a civil flight, a military orbit, a tanker, a vessel going dark, a SAR pass with footprint,
a ramping jamming cell, a NOTAM, a strike event.

---

## 2. Where the product stands (why UX is the gap)

- All 33 H19 backlog items are **code-complete and merged** (BACKLOG.md "ORIZONT 19", 33/33 ✅):
  the data path (Kafka → Redis/TimescaleDB), the 4D API, all five layers, recon prediction,
  CEP/anomaly engine, ontology, RBAC, provenance, cases, exports, vector tiles, observability, DR.
- The frontend *functions* (80 vitest tests, builds clean) but was built engineer-first. The
  2026-06-10 UX review's verdict: *"WorldView is notably less polished than the HUD on
  degradation/onboarding — its data layer and WebSocket resilience are sound; the gaps are
  UX-surface."* Its P1s are called **"the highest-value items in either frontend and worth a
  dedicated session."* This brief is the input to that session.
- Tracked as **TASK-4** in `BACKLOG.md` (🎨 P2, 13 SP, gated on the owner's manual test).
- The sibling product (the JARVIS HUD) already went through this maturation (see
  `docs/design/HUD_V2_BRIEF.md`) and sets the visual bar: dark cockpit, honesty badges
  (LIVE / DEMO / OFFLINE), first-run onboarding. WorldView should feel like the same family.

---

## 3. Scope of this engagement

**In scope (design, not code):**
- Information architecture + layout system for the whole WorldView screen (the panel zoo, §4).
- Visual design language applied to WorldView (token unification with the brand, §7).
- Every panel's states: loading / empty / error / disconnected / demo / first-run.
- New surfaces the review demands: map **legend**, **mode banner** (LIVE/HISTORICAL/REPLAY),
  **first-run & API-down explanation**, keyboard-shortcut **help overlay**, **demo badge**.
- Interaction model: selection → inspector → trail; alert → locate; replay; tour; export.
- Responsive behavior down to ~1024 px wide; accessibility (WCAG AA).

**Out of scope:**
- Backend/API changes (the API is rich; design against what exists — §5).
- New data layers or analytics; mobile-native app; marketing assets
  (separate brief: `docs/marketing/DESIGN_BRIEF.md`).
- Renaming the product or its agents.

**Priority order if you must cut:** the four P1s (§6.1) → legend + mode clarity → panel layout
system → everything else.

---

## 4. The current UI — complete inventory (from code, 2026-06-12)

A single full-bleed screen: a WebGL map/globe canvas with **ten absolutely-positioned overlay
panels** (plain Tailwind `div`s, no panel system, no drag/resize/collapse, all `z-10`).
Entry: `worldview/frontend/app/page.tsx`.

### 4.1 Layout map (current, 1440 px desktop)

```
┌────────────────────────────────────────────────────────────────────────┐
│ [Layers]                 [2.5D Map | 3D Globe]      [Stats HUD]        │
│  left-4 top-4              center top-4             [Export]  ⚠ BOTH  │
│                          [🎬 Tour AOIs]              right-4 top-4     │
│                            center top-16            (they overlap!)   │
│ [Recon · upcoming                                                      │
│  passes]                                                               │
│  left-4 top-[19rem]                                                    │
│  (hardcoded offset)              MAP / GLOBE                           │
│                                  (full viewport)                       │
│                                                                        │
│ [no-Mapbox hint]                                                       │
│  bottom-32 left-4                                                      │
│ [Inspector]                                          [Active alerts]   │
│  bottom-24 left-4                                     bottom-4 right-4 │
├────────────────────────────────────────────────────────────────────────┤
│ ▶ Play  ● LIVE  2026-06-12 06:41:03 UTC          speed [1×▾]          │
│ replay 06:26→06:41 (15m) [60×▾] ▶ Replay 🔗 Link                       │
│ ──────────────────────●────────────────────────── (24h range slider)   │
└────────────────────────────────────────────────────────────────────────┘
```

There is **no legend, no app header/wordmark, no settings, no auth UI, no help, no demo badge,
no responsive handling** (panels overlap below ~1280 px).

### 4.2 Panel-by-panel

All panels: `rounded-lg bg-cockpit/85 p-3 text-xs backdrop-blur` (cockpit = `#0a0e14`),
headers `font-semibold text-signal` (signal = `#38bdf8`), body `text-white/80`.

| Panel (file) | Position / size | Contents & actions | States today |
|---|---|---|---|
| **LayerPanel** (`components/LayerPanel.tsx`) | left-4 top-4 | Title "WorldView · Layers"; 5 checkboxes (Aircraft (ADS-B) / Vessels (AIS) / Satellites (SGP4) / GPS Jamming (H3) / Intel / Dark Vessels); when an entity is selected: "trail: `<id>` [clear]"; footer hint "click an entity to trace its path" (10 px, white/40) | none |
| **ReconPanel** (`ReconPanel.tsx`) | left-4 top-[19rem] (hardcoded below LayerPanel), w-64 | Title "Recon · upcoming passes"; rows like `SAR · NORAD 25544 · hormuz · in 12m · q0.87 ☀/🌙` (next 24 h, live countdown vs master clock); scrolls at max-h-56 | "No upcoming passes" — indistinguishable from "API down" |
| **ViewToggle** (`ViewToggle.tsx`) | top-center (left-1/2 top-4) | Segmented control "2.5D Map" / "3D Globe" | — |
| **CameraTour** (`CameraTour.tsx`) | top-center (left-1/2 top-16) | "🎬 Tour AOIs" → flies between AOI waypoints (FlyTo, loop), shows "→ ‹waypoint›"; any user pan/zoom cancels; "■ Stop tour" | — |
| **StatsHud** (`StatsHud.tsx`) | right-4 top-4, pointer-events-none | Title "On globe"; per-layer label + mono count; in historical mode a status dot per layer (loading white/40 · empty white/30 · error red-400 — tooltip-only explanations); in live mode a connection badge (… connecting · ⟳ reconnecting amber · ✕ disconnected red); "⚠ N dark vessels detected" red strip | the *only* health surface; dots fail WCAG contrast |
| **ExportPanel** (`ExportPanel.tsx`) | **right-4 top-4 — same coordinates as StatsHud; later in DOM so it paints on top** , w-64 | "⬇ Current view (GeoJSON)"; "Case id" input + [Brief] [GeoJSON]; "Reconstruction id" input + [GeoJSON] [JSON]; one-line status ("Exported 44 features" / "Export unavailable (offline / not built)") | graceful errors, but raw-id inputs presume you know ids |
| **AlertsPanel** (`AlertsPanel.tsx`) | bottom-4 right-4, w-64 | "Active alerts": severity dot (high red-400 / medium amber-400 / low sky-400) + label, e.g. `Dark vessel MMSI 123456 (gap 3600s)`, `airspace_closure (sev 0.8)`; click locatable alert → selects entity (Inspector + trail); scrolls at max-h-64 | "No active alerts" |
| **Inspector** (`Inspector.tsx`) | bottom-24 left-4, w-64 | Header `CONTEXT · 123456` + ×; raw key→value `dl` of ALL feature properties (mono, truncated); **Provenance · chain-of-custody** block: source / valid time / transaction time | "no data at the current time — scrub to where it was active"; "provenance unknown"; raw field names (`gs_kt`, `h3_index`) untranslated |
| **TimelineScrubber** (`TimelineScrubber.tsx`) | bottom, full-width bar (bg-cockpit/90) | Row 1: ▶ Play/⏸ Pause · **● LIVE** toggle (red bg when live, dim white/10 when not — easy to miss) · UTC clock · speed select (1/10/60/300×). Row 2: **ReplayControl** — `replay HH:MM:SS→HH:MM:SS (15m)`, speed (10/60/300×), ▶ Replay (drives master clock deterministically, % progress), 🔗 Link (copies `?from&to` reproducible URL). Row 3: 24 h range slider (`accent-signal`); dragging it switches to historical mode | scrubbing silently leaves LIVE; no tick marks, no event markers on the timeline |
| **Mapbox hint** (`DeckGlobe.tsx`) | bottom-32 left-4, 11 px, white/55 | "Showing coastlines (no Mapbox token). Set NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN for street tiles, or use 3D Globe." | map-mode-only, low contrast |

### 4.3 Map rendering & color encodings (exact values, `lib/deckLayers.ts`)

| Mark | Encoding |
|---|---|
| Aircraft (military) | dot r=3 px, **rgb(255, 92, 92)** |
| Aircraft (civil) | dot r=3 px, **rgb(80, 180, 255)** |
| Vessel | dot r=3 px, **rgb(120, 230, 180)** |
| Satellite | dot r=4 px, **rgb(240, 210, 120)**; footprint polygon same hue (fill α=40/255, line α=160) |
| Jamming cell (H3 polygon) | fill `[255, 180·(1−intensity), 40]` α=120 (yellow→red ramp), line rgb(255,140,40) |
| Intel zone/event | dot r=5 px or polygon, violet rgb(200,120,255) fill α=60, line α=200 |
| **Dark vessel** | dot r=5 px, **rgb(255, 70, 70)** |
| Selected-entity trail | white path, 2 px min, α=220 |
| Event callouts | TextLayer label = event category, 12 px, rgb(230,220,255), SDF outline dark |
| Globe backdrop (no Mapbox) | ocean rgb(10,18,28) sphere + landmasses + 30° graticule rgb(90,110,130) α=60 |
| Basemap (with token, 2.5D only) | Mapbox `dark-v11` |

⚠ **None of this is decodable by the user** — there is no legend anywhere (P1). Note the built-in
collisions to resolve: military aircraft red ≈ dark-vessel red ≈ alert red; civil-aircraft blue ≈
signal cyan (the UI accent).

### 4.4 Interactions

- **Hover** any pickable mark → black tooltip (deck.gl default style), per-layer formats, e.g.
  `UAL123 ⚑ MIL / alt: 10670m / gs: 480kt / track: 270°`, `NORAD 25544 / sensor SAR / v: 7.66km/s
  / target: ☀ daylight`, `H3 8a2a… / intensity: 0.82 / samples: 14`.
- **Click** an aircraft/vessel/satellite → selects it: Inspector opens, trailing-hour path draws,
  LayerPanel shows "trail: id". Click empty space or Esc → clears. (EW cells and context features
  are pickable for tooltips; only adsb/ais/tle are trackable.)
- **Click an alert** (if it has position+id) → selects that entity.
- **Keyboard** (`lib/useKeyboardShortcuts.ts`): `Space` play/pause · `L` go live · `←/→` scrub
  ±30 s (forces historical) · `Esc` clear selection. **Nothing in the UI reveals these** (P2).
- **Zoom** drives level-of-detail: below zoom 5, dense layers fetch 1-minute rollups; when a tile
  server is configured (`NEXT_PUBLIC_TILE_URL`) and zoom ≤ 6, aircraft/vessels switch to vector
  tiles (visually identical dots).

### 4.5 Modes & state matrix (what the design must make legible)

| Dimension | States | Where it shows today |
|---|---|---|
| Playback | **live** (default; WebSocket snapshot+deltas) / **historical** (as-of-T REST, debounced) / **replay** (deterministic window playback) | LIVE button tint; replay % on a small button — easy to miss you've left live (P1) |
| Live connection | connecting (default) / open / reconnecting / closed | small badge in StatsHud only |
| Per-layer fetch (historical) | loading / ok / empty / error | 1-dot-per-layer in StatsHud, tooltip-only meaning |
| Projection | 2.5D map (Mapbox if token, else coastline fallback + hint) / 3D globe (never Mapbox) | top-center toggle |
| Data reality | real OSINT feed / synthetic **demo feed** (START.bat default; rows tagged `source='demo'`) / nothing (first run, no API) | **nothing global** — demo is only visible if you open provenance on an entity; first-run = dark globe + tiny "✕ disconnected" (P1). This violates the platform's honesty system (§7) |
| Selection | none / entity selected (trail + Inspector) | Inspector presence |
| Camera | free / tour running (any interaction cancels) | tour chip top-center |

Defaults on load: live mode, playing, all 5 layers visible, 2.5D map, zoom 6 over Hormuz.

---

## 5. The data the UI must communicate (fields available per entity)

Design the Inspector/tooltips/legend against these (all already served by the API):

- **Aircraft:** `icao24`, `callsign`, `is_military`, `alt_m`, `gs_kt` (ground speed), `track_deg`.
- **Vessel:** `mmsi`, `sog_kt` (speed over ground), `cog_deg` (course).
- **Satellite:** `norad_id`, `sensor_type` (optical/SAR/coverage), `velocity_kms`, `is_sunlit`
  (can an optical sensor see anything?), `footprint` polygon.
- **Jamming cell:** `h3_index`, `intensity` (0..1), `sample_count`.
- **Context:** `kind` (`dark_vessel` / `event` / zone), `category` (e.g. `airspace_closure`,
  `strike`), `severity` (0..1), `mmsi` + `gap_seconds` (dark vessels), geometry point/polygon.
- **Every datum:** `source` + `ingested_at` → provenance: *valid time* (when it was true) vs
  *transaction time* (when WorldView recorded it). Jargon needs translation for users (P3).
- **Recon window:** `norad_id`, `aoi_id`, `sensor_type`, `t_ingress`/`t_egress`, `quality` (0..1,
  optical zeroed at night), `sunlit_at_peak`.
- **Alert:** kind (dark_vessel = always high severity / event), label, severity band, ts, position.
- **Cases & reconstructions** (backend-complete, UI = two raw id inputs today): cases have
  members/items/comments/audit history; exports = Markdown brief / GeoJSON / JSON; reconstructions
  = bounded time-window replays with shareable, reproducible exports.
- **Ontology** (API exists, zero UI): objects (Aircraft/Vessel/Satellite/AOI/ReconWindow/
  DarkVesselEvent) + links (covers / wentDark / inGeofence) + audited actions (annotate/watch).
  Not required scope, but the IA should leave room for object-centric navigation
  (entity page → linked objects) later.

---

## 6. Known UX problems — the redesign targets (ranked)

From `docs/2026-06-10-ux-review-hud-worldview.md` (static code review) **plus** findings from this
brief's own code pass (marked ★new).

### 6.1 P1 — must solve

1. **API-down / first-run is a dead end.** With no backend, the user gets a dark globe, zero
   counts, and a tiny status dot. No explanation, no recovery path ("start the API / run the demo
   feed / check NEXT_PUBLIC_API_URL"). The HUD already solved this with a first-run banner —
   WorldView needs its own designed first-run & degraded-state story.
2. **No legend.** Five layers, ~10 encodings (§4.3), zero decoding aid. Needs an always-reachable,
   ideally always-visible legend that doubles as the layer panel (toggle + decode in one place?).
3. **LIVE vs HISTORICAL vs REPLAY ambiguity.** A dim button is the only mode signal; arrow keys
   and the slider silently drop you out of live. Mode must be readable from anywhere
   (banner/frame/color shift), with an obvious one-click "go live" recovery.
4. **★new — StatsHud and ExportPanel are pinned to the *same* corner (right-4 top-4) and
   overlap**; Export (later in DOM) paints over the stats. Symptom of the real problem: no layout
   system. Design panel zones/docking with deliberate hierarchy: *monitor* (stats, alerts) vs
   *act* (export, tour) vs *inspect* (inspector, provenance) vs *navigate* (layers, timeline).

### 6.2 P2 — should solve

5. Keyboard shortcuts undiscoverable → design a `?` help overlay (and surface hints contextually).
6. Mapbox-token hint: tiny, low-contrast, map-mode-only — fold into a designed "basemap status".
7. Status-dot meanings are tooltip-only and fail WCAG contrast (`text-white/30` on near-black).
8. **★new — no demo badge.** The demo feed (the default out-of-the-box experience!) is only
   identifiable via per-entity provenance. The platform's honesty system (§7) requires a global,
   unmissable "DEMO / synthetic data" badge, like the HUD's amber ◐ DEMO.
9. **★new — ReconPanel's position is a hardcoded `top-[19rem]`** — breaks the moment LayerPanel
   grows; the "stack" must be a designed system, not magic numbers.
10. **★new — Export asks for raw `case-123` / `recon-456` ids** with no browse/list affordance —
    fine for v1, but design the panel so id entry feels intentional (recents, paste-target, help).
11. **★new — recon rows cram 6 facts into one truncating line** (`SAR · NORAD 25544 · hormuz · in
    12m · q0.87 ☀`); needs typographic hierarchy (what matters: *sensor + where + in how long*).

### 6.3 P3 — polish (design guidance welcome, don't over-invest)

12. No graticule coordinate labels; provenance jargon ("valid time"/"transaction time")
    unexplained; dark-vessel click shows generic props, not the *alert context* (gap duration,
    last-known vs dead-reckoned position); no responsive layout <1280 px (panels overlap); no
    WebGL-unavailable fallback design; Inspector shows raw field names (`gs_kt`) rather than
    human labels + units; timeline has no event markers (alerts/recon windows on the scrubber
    would make history *navigable*); empty states are bare one-liners; deck.gl default black
    tooltip is unstyled (off-brand).

---

## 7. Design language & brand constraints

Source of truth: `docs/BRAND_BOOK.md` §7 — *"WorldView's globe inherits the same void/cyan
language."* The product is part of the Jarvis Hub family (calm, premium, dark cockpit you
command); **restraint signals trust**.

**Brand palette (HUD V2 tokens) vs what WorldView currently uses — unify as part of this work:**

| Role | Brand token | WorldView today | Note |
|---|---|---|---|
| Background "void" | `#04070E` | `cockpit #0a0e14` | close, not identical |
| Text "ink" | `#EEF1F5` | `#e6edf3` | close |
| Accent "signal cyan" | `#2BB8F0` (light `#8FE0FF`) | `signal #38bdf8` (Tailwind sky-400) | pick one; propose the brand token |
| Status green | `#41F59B` | unused | available for "live/verified" |
| Status amber | `#FFB23F` | Tailwind `amber-400` ad hoc | demo/caution only |
| Alert red | `#FF5A52` | Tailwind `red-400/500` ad hoc | halt/danger only — sparingly |
| Violet | `#A78BFA` | intel layer ≈ rgb(200,120,255) | secondary accent |

**Typography:** brand = **Space Grotesk** (UI/display) + **JetBrains Mono** (data, timestamps,
ids, micro-labels, letter-spaced UPPERCASE). WorldView currently ships **system sans only** —
adopting the brand type ramp is in scope and will do a lot of the visual lifting. Numbers tabular.

**Art direction:** dark cockpit; thin glowing strokes; real data as texture; no mascots, no
gradient soup, no neon glow soup; generous void margins; left-aligned calm hierarchy; mono
micro-labels as a signature element.

**Map-color guidance:** the data encodings (§4.3) may be tuned (e.g. de-collide military-red vs
dark-vessel-red vs alert-red; reconsider civil-blue vs accent-cyan) but must stay legible on the
near-black basemap at 3 px dot sizes and remain distinguishable for color-blind users (add shape/
ring redundancy where possible — deck.gl supports per-point shapes at modest cost).

**The honesty system (non-negotiable, from MOONSHOT §5 + the HUD's precedent):** the UI never
passes seeded/demo data as real, never fakes a healthy state, and prefers an honest "offline,
here's what to do" over a silent empty screen. States to badge explicitly: LIVE (real feed) ·
DEMO (synthetic) · HISTORICAL (as-of T) · REPLAY · OFFLINE/DISCONNECTED.

**Learning from the benchmark's aesthetic — adopt the lesson, not the cosplay.** Sidhu's
WorldView gets its signature look from GLSL "lenses" (CRT scan lines, night-vision, FLIR,
military reticle), with this rationale: military display systems were *"engineered to extract
maximum information from sensor data"* — the look is a byproduct of information-density
discipline. **Adopt:** that discipline — every glow, color, and stroke must earn its place by
carrying information (this is already the brand's position). **Reject:** targeting-style UI —
no reticles, crosshairs, lock-on framing, or bounding-box "acquisition" effects. Our stated
lane is *"OSINT analysis & reconstruction, not operational targeting"* (`worldview/docs/
ROADMAP.md` §3), and tactical cosplay would undercut the calm-trust brand. **Optional (P3):**
*one* restrained cinematic "lens" as a view treatment for the tour/demo journey (§9.6) — e.g. a
subtle scanline or monochrome NVG-adjacent grade — clearly cosmetic, instantly dismissable,
honoring `prefers-reduced-motion`. Design it only if it stays calm; skip it without guilt.

**Design absence as signal ("negative space" intelligence).** The benchmark's most-quoted
insight: in OSINT, what *disappears* is the story — a vessel stops transmitting (dark vessel),
GPS confidence collapses (jamming), an airspace empties before a strike. *"When 3,400 flights
simultaneously clear an airspace, you don't need a security clearance to tell you what's
coming."* The current UI renders only presence (dots); give disappearance its own visual
grammar — last-known-position ghosts, gap markers on trails, deliberately-voided zones — so an
analyst reads a gap as *rendered evidence*, not as missing data. (Directly serves the
dark-vessel inspector context in §6.3.12 and the jamming layer's meaning.)

**Voice for UI copy:** calm, specific, declarative; butler not hype-man. "No vessels in this time
slice" beats "Nothing to see!". Every label should help an analyst trust the screen.

---

## 8. Technical & platform constraints (design within these)

- **Stack:** Next.js 14 (App Router) + TypeScript + TailwindCSS; deck.gl 9 (+ Mapbox GL only in
  2.5D mode); Zustand store. **No component library** — panels are hand-rolled Tailwind divs;
  designs must be implementable that way (or specify a minimal, dependency-light primitive set).
- **The canvas owns the viewport.** All UI floats over WebGL; overlays must manage
  `pointer-events` so the map stays interactive between panels (current code does this correctly
  — keep the discipline).
- **Globe mode has no basemap** (Mapbox can't render under deck's GlobeView) — the dark-earth +
  coastlines + graticule backdrop is ours and can be art-directed freely.
- **Performance:** target 60 fps with up to 50 k points per layer (API cap) and 1 M+ via vector
  tiles; avoid designs requiring per-frame DOM updates; the master clock ticks continuously
  (UTC readout updates every frame in live mode).
- **Hydration constraint:** time-derived values render only after mount (existing pattern —
  placeholders like `————… UTC` exist for this reason; design proper skeleton states for them).
- **Implementation reality:** the redesign will be built incrementally (per-panel PRs) by AI
  agents working from your spec — favor a tokens-first, component-by-component spec with exact
  Tailwind-expressible values over a big-bang layout that must land at once.
- **Basemap stance (vs the benchmark):** Sidhu's WorldView gets its wow from Google
  Photorealistic 3D Tiles — cloud-metered and closed. Our principles (local-first, every cloud
  hop opt-in — MOONSHOT §5) mean the Mapbox basemap is already our *one* optional cloud
  dependency, with a fully-local coastline fallback. Do **not** design presence that depends on
  photoreal cities; achieve it through abstraction — lighting, graticule, glow, motion, and the
  art-directable dark-earth globe (§8 bullet 3).
- **Env that shapes UX:** `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` (basemap or fallback),
  `NEXT_PUBLIC_API_URL` (default `http://localhost:4000`), `NEXT_PUBLIC_TILE_URL` (tile switch),
  `NEXT_PUBLIC_TOUR_AOIS` (tour waypoints). Auth exists server-side (JWT/RBAC, opt-in) but there
  is **no login UI** — out of scope, but don't design it into a corner.
- **A11y gaps to fix by design:** WCAG AA contrast (status dots currently white/30 on near-black),
  visible focus, focus trap for any modal/overlay you introduce, `prefers-reduced-motion`
  (tours/playback animations), don't rely on color alone (severity dots).

---

## 9. User journeys to design for

1. **First run (the owner, tonight).** Runs START.bat; demo feed on (or nothing, if API failed).
   Needs: instantly understand *what this is, what state it's in, what to do next* — and an
   unmissable "this is synthetic data" when in demo. This is the exact state the upcoming manual
   test starts from; it's the journey the review weighted highest.
2. **Ambient watch (analyst/desk).** WorldView on a second monitor over a choke point. Needs:
   glanceable health (live? lagging? layers ok?), alert salience without alarm fatigue, counts.
3. **Alert triage.** "⚠ dark vessel" appears (in-app, or via JARVIS digest with a deep link).
   Click → locate on map → inspect (who, gap duration, last known position) → trail → provenance
   ("which source said this, when") → export/attach to a case. Today this chain works but each
   hop is a different unstyled panel; design it as *one* coherent investigation flow.
4. **Event reconstruction (journalist).** Scrub back 6 h, find the moment, set a replay window,
   watch it at 60×, copy the reproducible link, export GeoJSON + case brief for the story. The
   timeline is the hero of this journey — today it's a bare range input with no event markers.
5. **Recon planning.** "When is the next SAR pass over my AOI?" — ReconPanel countdowns; needs
   hierarchy (next pass big, rest small) and a designed link to the map (show the pass footprint?).
6. **Showing it off (the demo path).** 3D globe + Tour AOIs is the wow moment; make tour state,
   waypoint labels, and exit affordance cinematic but on-brand (calm, not theme-park).

---

## 10. Success criteria (measurable)

- A first-run user with **no backend** can state, within ~10 s, what WorldView is, why the screen
  is empty, and what to do next (verbatim test in the owner's manual run).
- Demo/synthetic data is identifiable from **any** screenshot (global badge), per the honesty system.
- Every mark on the map is decodable via a legend reachable in ≤1 click (ideally 0).
- Current mode (LIVE / HISTORICAL / REPLAY) is identifiable from any corner of the screen at a
  glance, and recoverable to LIVE in one click from anywhere.
- No overlapping panels at 1280×800; usable (perhaps with collapsed panels) at 1024×768.
- All text + status indicators pass WCAG 2.1 AA contrast; severity/status never color-only.
- Keyboard shortcuts discoverable in-product (`?` overlay) without docs.
- The alert-triage chain (journey 3) flows through ≤3 visually-coherent surfaces.
- Zero "fake healthy" states: every loading/empty/error/offline state has designed copy + look.

---

## 11. Deliverables requested from Claude Design

In order — each is independently shippable to the implementing agents:

1. **Design tokens** — unified palette (resolve §7 table), type ramp (Space Grotesk + JetBrains
   Mono, sizes/weights/letter-spacing), spacing scale, panel anatomy (radius, blur, border,
   header style), elevation/z-order rules. Output: a tokens table mappable to
   `tailwind.config.ts` + `globals.css`.
2. **Layout & IA proposal** — panel zone system (which panels live where and why; collapse/
   minimize behavior; responsive strategy incl. <1280 px), with annotated wireframes for desktop
   + narrow. Resolve the right-corner collision and the hardcoded stack (§6.1.4, §6.2.9).
3. **The four P1 surfaces, fully specified** (all states + copy):
   a. First-run / connection overlay (no API · API up but empty · demo · WebGL unavailable);
   b. Legend (+ its relationship to the layer toggles);
   c. Mode system (LIVE/HISTORICAL/REPLAY banner or frame treatment + transitions);
   d. Right-rail reorganization (Stats/Export/Alerts).
4. **Per-panel redesign specs** for the remaining surfaces (§4.2): Inspector (humanized labels,
   units, the dark-vessel alert context, provenance in plain words), timeline (event markers,
   replay affordance, tick labels), ReconPanel, ExportPanel, tooltips (styled, on-brand),
   help overlay, demo badge.
5. **Interaction + motion spec** — selection/trail, alert→locate, tour, replay; durations/easing;
   whether/how motion *encodes information* (e.g. trail-recency fade, restrained flow textures —
   see the benchmark notes in §7) and the "negative space" grammar (last-known ghosts, trail-gap
   markers); the optional single demo "lens" treatment (§7) if it survives your judgment;
   `prefers-reduced-motion` fallbacks for all of it.
6. **Accessibility annotations** on all of the above.

**Format:** Markdown spec(s) with exact values (hex, px/rem, Tailwind classes welcome) +
low-fi layout sketches (ASCII or image). Figma optional — the implementers are code agents; an
unambiguous written spec beats pixels. Put final specs in `docs/design/` (suggested:
`WORLDVIEW_UX_SPEC.md`, companion to this brief).

**Suggested working order:** tokens → layout/IA → P1 surfaces → panels → motion. Ship after any
stage; the P1s alone are worth the session (per the UX review).

---

## 12. Glossary (the jargon a designer will hit)

| Term | Meaning |
|---|---|
| OSINT | Open-source intelligence — analysis from public data only |
| ADS-B | Aircraft position broadcasts; `icao24` = airframe hex id; callsign = flight code |
| AIS | Ship position broadcasts; `MMSI` = vessel id; SOG/COG = speed/course over ground |
| **Dark vessel** | A ship that stopped transmitting AIS in a watched zone — classic smuggling/sanction-evasion signal; position becomes *dead-reckoned* (estimated) |
| TLE / SGP4 | Public satellite orbit elements / the algorithm that propagates them; `NORAD id` = satellite number |
| Footprint | The ground area a satellite's sensor can see right now |
| Optical vs SAR | Camera (needs daylight — hence `is_sunlit`) vs radar (works at night) |
| Recon window | Predicted interval when a satellite's footprint covers an AOI (ingress→egress); quality 0..1 |
| AOI | Area of interest (e.g. Strait of Hormuz) |
| EW / GPS jamming / H3 | Electronic warfare; jamming intensity aggregated on H3 hexagonal grid cells |
| NOTAM | Official airspace closure/warning notice |
| Choke point | Strategic narrow passage (Hormuz, Suez…) |
| Master clock / as-of-T | The single timeline driving all layers; "state of the world at time T" |
| Valid vs transaction time | When a fact was true vs when the system recorded it (bitemporal provenance) |
| Provenance / chain-of-custody | Which source produced a datum and when — the trust trail |
| Tipping-and-cueing | One sensor's detection triggering another's attention (e.g. passes stacking over a strike zone) |
| Case / reconstruction | A shared investigation container with audit trail / a bounded, reproducible replay of an event window |
| LOD / MVT tiles | Level-of-detail: zoomed out, data switches to rollups/vector tiles for performance |

---

## 13. File map (for whoever implements the design)

| Surface | File |
|---|---|
| Screen composition | `worldview/frontend/app/page.tsx` (+ `app/layout.tsx`, `app/globals.css`) |
| Tokens | `worldview/frontend/tailwind.config.ts` (cockpit/signal) |
| Map/globe + backdrop + token hint | `worldview/frontend/components/DeckGlobe.tsx` |
| Data-layer styling (all map colors) | `worldview/frontend/lib/deckLayers.ts` · `lib/landLayer.ts` |
| Panels | `worldview/frontend/components/{LayerPanel,ReconPanel,ViewToggle,CameraTour,StatsHud,ExportPanel,AlertsPanel,Inspector,ProvenanceSection,TimelineScrubber,ReplayControl}.tsx` |
| Tooltip formats | `worldview/frontend/lib/tooltip.ts` |
| Shortcuts | `worldview/frontend/lib/useKeyboardShortcuts.ts` |
| State (modes, statuses, selection) | `worldview/frontend/lib/store/useTimelineStore.ts` |
| Data fan-out (live WS / historical REST) | `worldview/frontend/lib/useWorldViewData.ts` · `lib/api.ts` |
| Alert derivation | `worldview/frontend/lib/alerts.ts` |
| Brand | `docs/BRAND_BOOK.md` §7 · `docs/marketing/DESIGN_BRIEF.md` §1 |
| The UX review behind §6 | `docs/2026-06-10-ux-review-hud-worldview.md` |
| The benchmark, reverse-engineered | `docs/research/2026-06-12-bilawal-worldview-reverse-engineering.md` |
| Backlog tracking | `BACKLOG.md` → TASK-4 |

---

## 14. Handing this to Claude Design

- **Complete prompt = this file.** It contains everything: context (§1–2), scope (§3), the
  current UI with exact values (§4–5), the ranked problems (§6), constraints (§7–8), journeys
  (§9), the bar (§10), and what to produce (§11). Ask for the deliverables in §11's order.
- **If context is tight,** the minimum viable handover is §0, §3, §4, §6, §7, §10, §11.
- **Screenshots:** none exist for WorldView yet (the June-10 review rendered only the HUD).
  §4 is written to be sufficient without them; if the design session can run the stack
  (`worldview/README.md` quick start + `npm run db:seed`), real captures beat any inventory.
- **Don't redesign the brand** — apply it. Brand questions route to `docs/BRAND_BOOK.md`;
  open product questions route to the owner via `docs/OWNER_TASKS.md` conventions.
