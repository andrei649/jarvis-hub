# Jarvis Hub — HUD v2 · Handoff for Claude Code (Opus)

> **You are implementing the production HUD v2.** A high-fidelity, fully-interactive design prototype already exists in this project (`hud-v2.html` + `v2-*` modules). Your job: graduate it into the real app, wired to the live backend, and improve where production demands it. This doc maps the prototype, the design system, the data contract, and the decisions that frame the work.
>
> **Read order:** this file → `docs/design/HUD_V2_BRIEF.md` (the north star) → open `hud-v2.html` and click around → then `v2-style.css` and the `v2-*.jsx` modules.

---

## 0. North star (from the brief)

> *"A Bloomberg Terminal as Apple would have designed it in 2035, for one person who owns the whole machine."*

HUD v2 is a **redesign, not a reskin**. The hard problem is **information architecture** — ~30 capability areas, 228 endpoints, 16 agents — made **calm**. Principles: motion = real activity (restrained, honor `prefers-reduced-motion`); local-first and verifiable; one owner, full control. Bilingual (EN primary, RO real product copy).

---

## 1. What the prototype is (and isn't)

**Is:** a complete, clickable design spec for the v1 surfaces — real layout, real interactions, real copy, real data shapes.
**Isn't:** production-ready code. It's React-via-Babel in the browser (no build step, no types, mock data). That's deliberate — it optimizes for design iteration. **Do not ship it as-is**; port it (see §6).

### File map
| File | Role |
|---|---|
| `hud-v2.html` | Entry. Loads fonts, `v2-style.css`, React/Babel, then the modules **in order**. |
| `v2-style.css` | The entire design system as CSS variables + component classes. **Single source of truth for visuals.** |
| `v2-data.jsx` | All data on `window.V2` (roster, glyphs, tiers, dossiers, cognition scoring, trust/audit, memory/KG, decisions, weather/cal, **i18n EN+RO**). Mock — replace with live adapter. |
| `v2-primitives.jsx` | Icons (`ICONS`), `Icon`, `Glyph`, `Reactor`, `Meter`, `useClock`, time/date formatters, `statusClass`. |
| `v2-network.jsx` | `NetworkBrain` — the hero visualizer (orbiting agents, glowing core, collab beziers, live packets, click-to-focus). |
| `v2-cockpit.jsx` | `Conversation`, `CognitionStream` + `buildTrace`, `InputBar`, `renderRich`. |
| `v2-modes.jsx` | `AgentsMode` + `Dossier`, `TrustMode`, `MemoryMode`. |
| `v2-modes2.jsx` | `AutonomyMode`, `BuildMode`, `ObserveMode`, `InteropMode`. |
| `v2-modes3.jsx` | `ChatMode` (distraction-free), `CommsMode`, `AdminMode`. |
| `v2-modes4.jsx` | `FinanceMode`, `HealthMode`, `KnowledgeMode`, `FamilyMode` (agent "home" tabs). |
| `v2-shell.jsx` | `TopBar`, `Ticker`, `Rail`, `Tabs`, `RosterColumn`, `ContextColumn`, `Palette` (⌘K), `Ambient`, the `MODES` array. |
| `v2-app.jsx` | Root: state, hotkeys, submit→cognition flow, tweaks wiring, mount. |
| `tweaks-panel.jsx` | Design-tool tweak panel (host-protocol). **Prototype-only — drop in production.** |

### Babel-scope gotcha (why files look the way they do)
Each `<script type="text/babel">` is transpiled in **isolated scope**. Modules export to `window` via `Object.assign(window, {...})`, and consumers re-import at the top (`const { Icon, ICONS } = window;` and `const { useState } = React;`). **This whole pattern disappears when you move to a real bundler** — replace with normal ES `import`/`export`.

---

## 2. Modes (the IA)

`MODES` in `v2-shell.jsx` is the rail/tab source of truth.

**Built at fidelity (now all 8 capability modes):**
- **Cockpit** — daily driver. 3 columns: roster (left) · network brain + conversation/cognition (center) · context (decision queue, weather, schedule, heartbeat) (right).
- **Agents** — roster grid by tier → slide-in **Dossier** (soul, personality, runtime, plugins, collaborators).
- **Trust** — Merkle **audit chain**, physical **kill-switch**, **% local-vs-cloud** meter, capability grants, payments ledger.
- **Memory** — stats, fused recall, topic-decay, **bitemporal knowledge graph** with a time-travel slider.
- **Autonomy** (`v2-modes2.jsx`) — ranked morning brief, observer log, per-agent **AUTO/ASK/OFF policy** toggles with budgets.
- **Build** (`v2-modes2.jsx`) — **workflow DAG canvas**, skills marketplace (install toggles), router sandbox.
- **Observe** (`v2-modes2.jsx`) — quality stats, recent **traces with stage breakdowns**, model arena, per-agent latency, resilience.
- **Interop** (`v2-modes2.jsx`) — A2A peers, MCP servers, widgets, webhooks (in/out).
- **Chat** (`v2-modes3.jsx`) — distraction-free direct line to Jarvis. Reuses cockpit `Conversation` + `InputBar` on the **same `messages` state**; hides the situation ticker (`mode==='chat'`). Hotkey `9`.
- **Comms** (`v2-modes3.jsx`) — unified inbox across Telegram/email/WhatsApp/voice; channel filters + reading pane; shows which agent handled each thread. Hotkey `0`.
- **Admin** (`v2-modes3.jsx`) — models & backends, plugin registry (toggles), API keys, channels, backups, host. **This is the D3 "Admin as a mode" unification, realized.**
- **Finance · Health · Knowledge · Family** (`v2-modes4.jsx`) — agent "home" tabs (Gecko / Hercules / Vision / Frigga). Family is the **local-only** privacy space.

**All 15 modes built.** See **`docs/design/HUD_V2_NAVIGATION_MAP.md`** for the full map (every mode → component → data key → hotkey).

> Modes 5–8 (`v2-modes2.jsx`) are wired exactly like the core four: hotkeys `5`–`8`, ⌘K entries, `workzone full` render in `v2-app.jsx`. Their data lives on `window.V2.{AUTONOMY,BUILD,OBSERVE,INTEROP}` — same mock-then-wire story as §5.

**Navigation is a live toggle** (`ia` state: `rail` | `tabs`) — see D1. Default `rail`. ⌘K command palette jumps anywhere.

---

## 3. Signature interactions (nail these in production)

1. **Cognition trace** (`buildTrace` in `v2-cockpit.jsx`) — on submit, runs classify → route → gather → synthesize, scoring agents against `COGNITION_SCORING` keywords and rendering the routing table live. In production this should **stream from the real orchestrator** (SSE), not a setTimeout sequence — keep the same 4-stage visual.
2. **Network brain + focus** (`NetworkBrain`) — click a node to dim non-neighbors and reveal its collab links; click the core to reset. Packets animate only when `motion !== 'calm'`.
3. **Merkle audit chain** (`TrustMode`) — hash-linked sealed blocks (`AUDIT_CHAIN`). Production: render the real append-only log; verify hashes client-side.
4. **% local meter** — `localPct` is hard-coded `87`. Wire to real compute-locality telemetry.
5. **Kill-switch** — local toggle in proto; must hit the real halt-all endpoint with a confirm step.

---

## 4. Design system (in `v2-style.css`)

Everything is driven by `data-*` attributes on `.hud-root`:
- `data-look`: `obsidian` (default, glowing/cyber) · `graphite` (matte, larger radii, no brackets/glow).
- `data-accent`: `cyan` · `amber` · `green` · `violet` (swaps `--accent*` + `--panel-line` + `--bracket`).
- `data-density`: `compact` · `normal` · `comfy` (scales `--pad`, `--gap`, font-size).
- `data-motion`: `calm` · `lively` (gates packet/ambient animations).
- `data-scanline`, `data-dotgrid`: `on`/`off` ambient texture layers.

**Type:** Space Grotesk (UI) + JetBrains Mono (numerals/labels). Currently from Google Fonts CDN — **self-host in production** (the repo already vendors fonts; follow the `fonts.css` pattern). Numerals/metrics are always mono + `tabular-nums`.

**Tokens:** near-black `--void`, translucent `--surface`, faint `--panel-line`, status colors (green/amber/red/violet). Panels use corner-bracket frames (`.bk`) in obsidian. Keep this token layer intact — Admin (D3) is meant to drop in with **zero new colors**.

**Motion:** entrance states animate *from* hidden so print/reduced-motion show content. No infinite decorative loops on content.

---

## 5. Data contract

Prototype data lives on `window.V2` (`v2-data.jsx`). The real source is the existing **`data.js`** adapter, which already fetches:
`/api/agents` · `/status` · `/dashboard` · `/tasks` · `/ticker`.

**Migration:** replace `window.V2.*` reads with the `loadJarvisData()` shape from `data.js`. The prototype's roster/glyphs/tiers/dossiers/cognition-scoring were lifted verbatim from product `data.js`, so they already match — `JARVIS_GLYPHS`, `JARVIS_TIERS`, `JARVIS_AGENT_META`, `COGNITION_SCORING`, `DOSSIER`, `PLUGINS`, `MEMORY_STATS`, etc. are the real keys.

**i18n:** `V2.I18N.{en,ro}` is a flat key→string map; `lang` state swaps it. Romanian strings are real product copy — keep verbatim, don't machine-translate.

Endpoints that still need a home in the UI: streaming cognition (SSE), audit-log read, compute-locality telemetry, kill-switch action, payments approval.

---

## 6. Implementation plan (recommended path)

Assuming D1/D4 stand and D2=Vite/TS, D3=unify (see `hud-v2-decisions.html`):

1. **Scaffold** Vite + React + TS. Self-host fonts.
2. **Port `v2-style.css` as-is** (it's framework-agnostic). This locks the look immediately.
3. **Port `v2-data.jsx` → typed models**, then swap mock for `data.js`'s `loadJarvisData()`. Define TS types for the agent/dossier/trace/KG shapes.
4. **Port primitives → shell → modes** (drop the `window` re-import pattern; use ES modules). Keep component boundaries 1:1 — they're already clean.
5. **Wire live data + SSE** for the cognition trace and ticker.
6. **Replace `tweaks-panel.jsx`** with real user settings (the tweak axes — accent/density/motion/lang/texture — become genuine preferences persisted server-side).
7. **D3:** fold Admin into the shell as a mode using the existing tokens.
8. **Fast-follow modes** on the same primitives: Autonomy → Observe → Build → Interop.

---

## 7. Improvement backlog (use judgment)

- **Cognition stream**: make it real SSE; show token-by-token synthesis; surface actual plugin reads + redactions.
- **Network brain**: physics/force layout instead of fixed rings once agent count varies; real packet routing tied to live tasks.
- **KG browser**: load the real bitemporal graph; the slider should query "as-of" snapshots, not filter a static `born` field.
- **Trust**: real Merkle verification with a visible "tamper check" action; kill-switch confirm + audit entry.
- **Accessibility**: keyboard nav for the network nodes and palette is partial — complete it; ARIA on status dots/meters.
- **Performance**: the always-on ticker/packets/clock should pause when the tab/wall-display is idle; respect `prefers-reduced-motion` (already gated in CSS — extend to JS timers).
- **Ambient mode**: deepen it (next decision, glanceable health) for the 24/7 wall display.
- **Responsive**: the cockpit 3-column collapses poorly under ~1100px — define breakpoints.

---

## 8. Known prototype quirks (not bugs to chase)

- **Thumbnail/screenshot tools render the main area black/white.** This is an html-to-image limitation with `backdrop-filter` + `mask-image` + heavy SVG — **the real browser renders it correctly** (verified across all four modes). Don't "fix" it by removing the effects unless you want max screenshot-tool compatibility.
- **Cognition timing** is a `setTimeout` sequence (`v2-app.jsx`) standing in for the real stream.
- **`localPct`, audit hashes, weather, calendar** are mock constants — all flagged above.

---

## 9. Decisions reference

See **`hud-v2-decisions.html`** (sign-off page) for D1–D4 with options, recommendations, and tradeoffs. **All four are locked:**
- **D1 IA** → rail + ⌘K (resolved/prototyped; tabs available as toggle)
- **D2 Stack** → **Vite + React + TS** (✅ approved by owner)
- **D3 Admin** → **unify** — Admin becomes a mode in the v2 shell (✅ approved by owner)
- **D4 Scope** → Cockpit+Agents+Trust+Memory (resolved/prototyped)

All decisions confirmed — scaffold and build per §6. No further sign-off needed before starting.
