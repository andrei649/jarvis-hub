# WorldView — UX Spec (companion to WORLDVIEW_UX_BRIEF.md v1.1)

> Deliverables 1–5 from the brief §11, in implementation order. Every value is Tailwind-expressible.
> The hi-fi mock (`WorldView Redesign.html` in the design project) demonstrates all of this live —
> its Tweaks panel switches the six scenario states (LIVE / DEMO / HISTORICAL / REPLAY / OFFLINE / FIRST-RUN).

---

## 1. Design tokens

### 1.1 Palette (resolves brief §7 table — brand tokens win)

| Token | Value | Tailwind name | Use |
|---|---|---|---|
| `void` | `#04070E` | `bg-void` | app bg (replaces `cockpit #0a0e14`) |
| `void-2` | `#070D18` | `bg-void-2` | inputs, wells |
| `surface` | `rgba(9,16,28,.82)` | `bg-surface` | panel bg (+ `backdrop-blur-[10px]`) |
| `surface-2` | `rgba(12,21,36,.92)` | `bg-surface-2` | app bar, timeline, overlays |
| `line` | `rgba(139,196,240,.14)` | `border-line` | panel borders |
| `line-2` | `rgba(139,196,240,.07)` | `border-line-2` | row separators |
| `signal` | `#2BB8F0` | `text-signal` | accent (replaces sky-400 `#38bdf8`) |
| `signal-light` | `#8FE0FF` | | panel titles, emphasized data |
| `ink` | `#EEF1F5` / `.64` / `.38` / `.2` | `text-ink…` | 4-step text ramp |
| `green` | `#41F59B` | | LIVE, verified, ws-open |
| `amber` | `#FFB23F` | | DEMO, caution, degraded |
| `red` | `#FF5A52` | | alerts, dark vessels, offline — sparingly |
| `violet` | `#A78BFA` | | REPLAY, intel layer |

### 1.2 Map encodings (de-collides §4.3 — color + SHAPE, never color alone)

| Mark | Shape | Color | Was |
|---|---|---|---|
| Civil aircraft | filled chevron ▲ | `#7FB4E8` steel blue | blue dot (≈accent collision) |
| Military aircraft | **hollow** chevron | `#FFB23F` amber | red dot (≈alert collision) |
| Vessel | filled diamond ◆ | `#5FE0B0` seafoam | green dot |
| Dark vessel | **hollow ring + pulse** | `#FF5A52` red | red dot (≈mil collision) |
| Satellite | dot + orbit ring ◎ | `#E8D27A` gold | yellow dot |
| Jamming cell | H3 hex fill | ramp `rgba(255, 180·(1−i)+40, 40)` | unchanged |
| Intel event/zone | filled square ■ / dashed poly | `#A78BFA` violet | unchanged |
| Selected trail | solid white path, gradient tail | `#EEF1F5` α .85 | unchanged |
| Dead-reckoned path | dashed red `5 4`, last-fix ghost ring | `#FF5A52` α .55 | **new** |

Red now means exactly one thing: *something is wrong* (dark vessel, alert, offline). Military is amber (caution), and no marker uses the UI accent cyan.

### 1.3 Type ramp

| Role | Font | Size/weight/tracking |
|---|---|---|
| Panel titles | JetBrains Mono | 9px · 500 · `.16em` · UPPERCASE · signal-light |
| Micro-labels / meta | JetBrains Mono | 8–9.5px · 400 · `.04–.14em` · ink-3 |
| Data values | JetBrains Mono | 10–15px · tabular-nums |
| Body / labels | Space Grotesk | 11–13px · 400–500 |
| Overlay titles | Space Grotesk | 21px · 600 |
| Master clock | JetBrains Mono | 13–14px · tabular-nums |

Load via `@fontsource/space-grotesk` (400/500/600/700) + `@fontsource/jetbrains-mono` (400/500/600/700) — self-hosted, no CDN.

### 1.4 Panel anatomy

`rounded-md (6px) · bg-surface · border border-line · backdrop-blur-[10px]`; header row `px-3 py-2 border-b border-line-2` with mono title + right-aligned mono meta + optional collapse chevron; body `p-3 overflow-y-auto overflow-x-hidden`. Scrollbars 4px, thumb `line`. Z-order: map 0 · panels 10 · tooltips 40 · app bar/timeline 50 · mode frame 60 · overlays 80.

---

## 2. Layout & IA — the zone system

```
┌─ mode frame: 2px top strip, colored by mode ───────────────────────────┐
│ APP BAR (46px): wordmark · AOI chip · 2.5D/3D seg · tour ··· mode pill │
│                 · clock · conn badge · ?                                │
├─────────────────────────────────────────────────────────────────────────┤
│ NAVIGATE (left, 252px)   MAP (owns viewport)    MONITOR/INSPECT (right, │
│  · Layers+Legend                                 286px)                 │
│  · Recon next passes                              · On globe (stats)    │
│                                                   · Inspector (when     │
│                                                     selection)          │
│                                                   · Active alerts       │
│                                                   · Export (collapsed)  │
├─────────────────────────────────────────────────────────────────────────┤
│ TIMELINE (~95px): transport · LIVE · clock · mode note · replay · speed │
│                   24h scrubber + event markers + ticks                  │
└─────────────────────────────────────────────────────────────────────────┘
```

- Zones are flex columns with `gap-2.5` — **no hardcoded offsets** (kills `top-[19rem]`); panels stack and the column scrolls if needed.
- Right-corner collision resolved: **StatsHud top-right; Export docked bottom-right, collapsed by default** (header-only strip).
- Top-center is reserved for nothing at rest — ViewToggle + Tour move into the app bar.
- Alert→locate→inspect is one rail: alerts (bottom-right) opens Inspector directly above it; both share the right rail = journey 3 in ≤3 coherent surfaces.
- Responsive: <1280px collapse Legend + Recon to icon strips (header-only, expand on hover/tap); <1024px also drop Export and Stats into a single "status" disclosure. Panels never overlap by construction.

## 3. The four P1 surfaces

### 3.1 First-run / API-down overlay
Centered 520px card over dimmed map (`brightness(.45)`), shown when: first load with no API, or WS closed >60s with zero cached data. Copy (exact):
- **Title:** "WorldView is up — its data feed isn't."
- **Body:** "This screen fuses live aircraft, vessels, satellites, GPS-jamming and intel onto one time-scrubbable map. Right now the API at `localhost:4000` isn't answering, so the globe is empty."
- **Steps:** 1) Start the backend — `START.bat` boots the API + a synthetic Hormuz demo feed · 2) Or point at a running API — set `NEXT_PUBLIC_API_URL` and reload · 3) Then take the tour — press `?` for shortcuts.
- **Honesty footer:** "◐ The demo feed is synthetic — WorldView will badge it. It never passes demo data as real." + RETRY button.
- Variants: *API up but empty* — same card, title "Connected — no data in this window yet", steps swap to seed/scrub. *WebGL unavailable* — title "This machine can't render the globe", offer table view + docs link.

### 3.2 Legend = the layer panel
One panel, top-left: each row is checkbox + **shape glyph** (the actual map mark, same SVG) + name + live count. Toggling off dims the row. Sub-encodings (military, dark vessel) indent under their layer. Footer rows decode trail + dead-reckoned path. Zero clicks to reach; collapse chevron for ambient use.

### 3.3 Mode system
Three reinforcing signals, all driven by one store value:
1. **Mode frame** — 2px top border across the whole app: green LIVE · amber DEMO · cyan HISTORICAL · violet REPLAY · red OFFLINE.
2. **Mode pill** (app bar, always visible): dot + word + note ("· as of 06:12:30 UTC"); in HISTORICAL/REPLAY it grows a **GO LIVE** button.
3. **Timeline restates it** — clock shows the *viewed* time; a mode note explains it ("VIEWING THE PAST — world state as of this moment"); the LIVE button is filled green when live, hollow when not (one click back, plus `L`).
DEMO additionally watermarks the map corner: "◐ SYNTHETIC FEED — NOT REAL-WORLD DATA". Transition: 200ms color fade; reduced-motion: instant.

### 3.4 Right-rail reorganization
Stats ("On globe") top: shape glyph + label + tabular count per layer; per-layer status dots only in historical (loading/empty/error as ◌/—/✕ with text, AA contrast ink-3 minimum); dark-vessel strip (`role="alert"`) below counts. Inspector opens between Stats and Alerts. Export bottom, collapsed; expanded = current-view button + case/recon id inputs with `recent: case-7 recon-12` paste-targets.

## 4. Panel specs (remaining)

- **Inspector** — humanized labels with units (`Last speed / course · 11.2 kt · 312°`, never `sog_kt`); dark-vessel selections show **alert context first**: Last AIS fix · Silent for (red) · Position now: dead-reckoned (amber). Provenance in plain words: "Reported by AISStream — true at 05:41:03, recorded by WorldView at 05:41:07. Position since then is estimated from last course and speed." Actions: TRAIL (primary) · WATCH · + CASE · EXPORT.
- **Recon** — hierarchy: sensor chip (SAR gold / OPTICAL cyan) + big mono countdown ("in 12m") + quality (green ≥.7, amber below); second line NORAD · AOI · ☀/☾ · note. Rows with q<.5 at 55% opacity. Hovering a row should highlight the pass footprint on the map (motion spec §5).
- **Timeline** — 24h track with tick labels (-24h…now); **event markers**: red = alerts, gold = recon passes, violet = intel; hover shows label tooltip, click scrubs there. Replay window = violet bracket on the track + chip in the transport row with COPY LINK / STOP. Scrubbing the track enters HISTORICAL explicitly (mode system fires).
- **Tooltips** — replace deck.gl default: `bg-surface-2 border border-signal-dim rounded-md px-3 py-2`, mono id line + mono kv lines, 9px.
- **Help overlay** (`?`) — shortcut grid (Space · L · ←/→ · Esc · 1–5 · G · R · ?), closes on Esc/click-out, focus-trapped.
- **Demo badge** — pill in app bar (amber ◐ DEMO · synthetic data) + map watermark; both bound to feed source, not env.

## 5. Motion & accessibility

### 5.0 The negative-space grammar (brief §7 — disappearance as rendered evidence)

Absence gets its own visual vocabulary; an analyst must read a gap as evidence, not missing data:

| Pattern | Rendering | Where |
|---|---|---|
| **Signal-loss marker** | dashed ghost ring + small × at the exact last fix, mono caption `signal lost HH:MM` | end of any track whose feed stopped |
| **Solid → dashed trail** | past track solid (layer color); after loss, dead-reckoned path dashed red `5 4` | dark vessels |
| **Uncertainty cone** | faint red wedge from last fix widening along DR heading; label `DR ±2.1nm` | dark vessels, position estimate |
| **Voided zone** | dashed ink-outline polygon (no fill), ghost outlines of *departed* marks (dashed, 28% α), caption `AIRSPACE VOIDED — 14 TRACKS DEPARTED IN 22M` | airspace emptying, pre-event |
| **Jamming** | H3 ramp (existing) — reads as "GPS confidence collapsing here" | EW layer |

Rule: ghosts and voids never animate (stillness *is* the signal); only live alerts pulse.

### 5.1 The arrival moment (brief §1 — deep link from JARVIS/Argus)

Landing via `?from&to` (+entity): camera pre-positioned on the entity, replay window pre-set (violet bracket on the timeline), Inspector open, and an **arrival banner** top-center: `◈ ARGUS · VIA JARVIS DIGEST — Dark vessel · MMSI · geofence · window 05:26→06:41 pre-set` with `▶ REPLAY THE GAP` (primary) and `DISMISS`. Banner enters 500ms ease-out slide; reduced-motion: instant. Mode = REPLAY (violet frame) from the first frame — never fake-LIVE.

### 5.2 The demo lens (brief §7 — optional, judged worth keeping)

One restrained treatment for the tour/demo journey only: a 1px/3px scanline screen-blend at 2.2% opacity + soft vignette. No reticles, no FLIR, no lock-on. Always paired with a dismiss chip (`LENS · MONO GRADE ✕ OFF`); `prefers-reduced-motion` hides it entirely; never on by default; never in screenshots/exports.

### 5.3 Durations & a11y

- Durations: panel collapse 160ms ease-out; mode-frame fade 200ms; alert ring pulse 2s loop; dark-vessel pulse 2s loop; arrival banner 500ms; tour camera = deck.gl FlyTo ≥1200ms with banner "→ waypoint".
- `prefers-reduced-motion`: all loops/pulses off (static ring), transitions instant, tour becomes cut-not-fly.
- A11y: all text ≥ ink-3 on void (AA); status never color-only (shape glyphs, sev tags HIGH/MED/LOW, mode words); `:focus-visible` 2px signal outline on every control; overlays focus-trap + Esc; timeline is `role="slider"` with keyboard ←/→; alerts list `role="button"` rows; live-region (`role="alert"`) for new high-severity alerts.

## 6. Implementation order (per-panel PRs)

1. tokens → `tailwind.config.ts` + `globals.css` + fontsource imports
2. zone system in `page.tsx` (flex columns; delete absolute offsets)
3. mode system (store + frame + pill + timeline restate) — biggest UX win
4. Legend/LayerPanel merge · 5. first-run overlay · 6. right rail + Inspector rewrite · 7. timeline markers + replay chip · 8. tooltips/help/demo badge · 9. map encoding shapes (deckLayers.ts: `getIcon`/shape per type) · 10. negative-space grammar (ghosts/cones/voids in deckLayers.ts) · 11. arrival banner bound to `?from&to` parse

## 7. Benchmark stance (brief §7, for reviewers)

Vs. Sidhu's WorldView: we adopt the information-density discipline (every stroke carries data) and reject targeting cosplay (no reticles/lock-on). Our visible differences ship in this design: provenance one click away (Inspector), honesty badges (mode system + demo watermark), reproducible replay links (timeline chip), self-hosted dark earth (no photoreal cloud dependence). The globe stays abstract by principle — presence through lighting, graticule, and live data as texture.
