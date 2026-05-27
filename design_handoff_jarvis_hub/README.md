# Handoff: JARVIS HUB v0.2.1 — HUD redesign

## Overview

This is a complete UI redesign for **JARVIS HUB** — Andrei's local-first multi-agent AI orchestration system (15 agents, Python/aiohttp on `localhost:8765`, LM Studio backend). The goal of the redesign is to replace the current simple chat page with a sci-fi HUD interface: a 3-column dashboard with an animated voice visualizer, live agent network, conversation area, and ambient widgets (weather, calendar, agents grid, heartbeat alerts).

The aesthetic target is **"Bloomberg Terminal if Apple had designed it in 2035"** — geometric but not rigid, dark but not depressing, technical but not intimidating. Original interface design — no recreation of any branded/copyrighted UI.

---

## About the design files

The files in `design/` are **design references created as a self-contained HTML prototype** using React + Babel for fast iteration. They are not production code to drop into the project as-is.

**The implementation task is to recreate this design in the existing Python/aiohttp codebase** (`cabinet/agents/web/index.html` + `cabinet/agents/web.py`), splitting the prototype into the three target files:

```
cabinet/agents/web/
├── templates/
│   └── index.html        ← page shell (head, fonts, root divs)
├── static/
│   ├── style.css         ← all CSS from <style> block in design/index.html
│   └── app.js            ← vanilla JS port of app.jsx + components.jsx
```

You can either:
- **Option A (recommended for fastest delivery):** Port React → vanilla JS. The interactivity is light — state is a plain object, DOM is rebuilt on state change. This drops the React/Babel runtime cost (~150 KB) and matches the project's no-bundler philosophy.
- **Option B:** Keep React via CDN, copy the JSX files as-is. Babel-in-browser is fine for a localhost-only app.

The data layer (`data.js`) is mock — replace with real fetch calls to existing endpoints (see API section).

---

## Fidelity

**High-fidelity.** Colors, typography, spacing, animation timing, and interactions are all final. Recreate pixel-perfectly. Every value below is exact.

---

## Tech context (existing project)

- **Backend:** Python 3.12 + aiohttp on `http://127.0.0.1:8000` (note: original brief said 8765 — confirm port)
- **LLM:** LM Studio on port 1234 with `google/gemma-4-26b-a4b`
- **Existing endpoints (already implemented):**

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Dashboard HTML |
| GET | `/status` | `{ llm_backend, agents: [...] }` |
| GET | `/agents` | Agent list |
| GET | `/dashboard` | `{ weather, news, system, conversation }` |
| POST | `/chat` | `{ message }` → `{ response, agent }` |
| POST | `/chat/stream` | SSE: `data: { token: "..." }` then `data: { done: true }` |
| GET | `/memory`, `/sessions`, `/learning`, `/security`, `/bench` | Diagnostics |

- **No WebSocket yet** — the design assumes one at `/ws` for live events (`voice_state_change`, `heartbeat_alert`, `agent_status_change`, `proactive_message`). **You will need to add this** to `cabinet/agents/web.py`. If you can't add it in this pass, fall back to polling `/dashboard` every 30s for ambient data and use the existing SSE stream for chat.

---

## Layout

Full-viewport, no scroll on the document. Internal scroll on left/right panels and conversation.

```
┌────────────────────────────────────────────────────────────────────┐
│  TopBar  (logo · clock · status badges)              ~78px height  │
├──────────┬─────────────────────────────────────┬───────────────────┤
│ Agent    │   Voice HUD (fixed height ~220px)   │  Weather          │
│ Network  ├─────────────────────────────────────┤  Calendar         │
│          │                                     │  Agents Grid      │
│ ──────   │   Conversation (flex-1, scrolls)    │  Heartbeat Feed   │
│ System   │                                     │                   │
│ stats    ├─────────────────────────────────────┤  (all scroll      │
│          │   Input bar  (fixed height ~48px)   │   internally)     │
│ 280px    │             flex-1                  │   320px           │
└──────────┴─────────────────────────────────────┴───────────────────┘
```

**Grid:**
- `body` → `display: flex; flex-direction: column; height: 100vh; overflow: hidden`
- `.hud-main` → `display: grid; grid-template-columns: 280px 1fr 320px; gap: 14px; padding: 14px; flex: 1; min-height: 0`
- Panels: `display: flex; flex-direction: column; gap: 14px; min-height: 0`
- Left/right panels: `overflow-y: auto`

**Responsive breakpoints:**
- `<= 1280px`: side panels shrink to `240px / 280px`, clock font 36px
- `<= 1024px`: side panels shrink to `200px / 240px`, agent items hide the model badge column
- `<= 768px` (mobile): currently not designed. If needed: collapse left into a hamburger drawer, right into tabs.

---

## Design tokens

```css
:root {
  /* Backgrounds */
  --bg-void:        #030810;   /* page bg */
  --bg-surface:     #07111f;   /* card surface */
  --bg-glass:       rgba(0, 174, 239, 0.04);
  --border-glass:   rgba(0, 174, 239, 0.12);
  --border-active:  rgba(0, 174, 239, 0.35);

  /* Accent (cyan default; user-switchable via Tweaks) */
  --accent:         #00AEEF;
  --accent-light:   #7FDBFF;
  --accent-dim:     rgba(0, 174, 239, 0.4);   /* color-mix 40% */
  --accent-faint:   rgba(0, 174, 239, 0.1);   /* color-mix 10% */
  --accent-glow:    rgba(0, 174, 239, 0.35);  /* color-mix 35% */

  /* Status */
  --green-active:   #39FF8B;
  --green-dim:      rgba(57, 255, 139, 0.5);
  --amber-warn:     #FFB23F;
  --red-alert:      #FF453A;

  /* Text */
  --text-primary:   #E8F4FD;
  --text-secondary: rgba(232, 244, 253, 0.6);
  --text-dim:       rgba(232, 244, 253, 0.28);

  /* Typography */
  --font-ui:        'Exo 2', system-ui, sans-serif;
  --font-mono:      'Share Tech Mono', ui-monospace, monospace;

  /* Spacing (density-driven) */
  --pad-panel:      16px;    /* compact: 11px, comfy: 22px */
  --gap-panel:      14px;    /* compact: 10px, comfy: 20px */
}
```

**Alternative accent palettes** (cycled via Tweaks):
| Theme  | --accent  | --accent-light |
|--------|-----------|----------------|
| Cyan   | `#00AEEF` | `#7FDBFF`      |
| Amber  | `#FFB23F` | `#FFD787`      |
| Green  | `#39FF8B` | `#9CFFD2`      |
| Violet | `#9B6BFF` | `#D0B6FF`      |

**Fonts:** Load via Google Fonts:
```html
<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@200;300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
```

**Typography scale:**

| Use                              | Font            | Size  | Weight | Letter-spacing |
|----------------------------------|-----------------|-------|--------|----------------|
| Clock (main)                     | Share Tech Mono | 44px  | 400    | 0              |
| Logo "JARVIS·HUB"                | Exo 2           | 17px  | 700    | 0.18em         |
| Body / conversation text         | Exo 2           | 13.5px| 400    | 0              |
| Agent name                       | Exo 2           | 13px  | 500    | 0.04em         |
| Bracket label (UPPERCASE)        | Exo 2           | 10px  | 600    | 0.18em         |
| Status badge label               | Exo 2           | 8px   | 600    | 0.18em         |
| Agent role / meta text           | Share Tech Mono | 9–10px| 400    | 0.05–0.1em     |
| Status badge value               | Share Tech Mono | 11px  | 400    | 0.06em         |
| Sys-panel values                 | Share Tech Mono | 11px  | 400    | 0              |
| Conversation tag `[JARVIS]`      | Share Tech Mono | 10px  | 700    | 0.08em         |
| Weather temp                     | Share Tech Mono | 42px  | 400    | 0              |
| Voice viz readout label          | Share Tech Mono | 11px  | 400    | 0.18em         |
| Forecast/timestamps              | Share Tech Mono | 10px  | 400    | 0              |

---

## Components

### 1. TopBar (`.topbar`)

- 3-column grid: `1fr auto 1fr`
- 14px 24px padding
- `border-bottom: 1px solid var(--border-glass)`, plus two `::before/::after` accent glow lines at the bottom corners (35% width each, gradient fades to transparent)
- `background: linear-gradient(180deg, rgba(0,174,239,0.05) 0%, rgba(0,174,239,0.01) 100%)`
- `backdrop-filter: blur(8px)`

**Logo (left):**
- SVG arc-reactor mark (22×22): three concentric circles + 4 cardinal tick lines, fill var(--accent). Animates `rotate(360deg)` over 60s linear infinite.
- Right of mark: stacked `JARVIS·HUB` (17px Exo 2 700) over `v0.2.1 · BONOBO-WS` (10px Share Tech Mono, var(--text-dim))

**Clock (center):**
- Live `HH:MM:SS` in 44px Share Tech Mono var(--accent), `text-shadow: 0 0 18px var(--accent-glow)`
- Below: `DAY · DD MON YYYY · EUROPE/BUCURESTI` in 10px Share Tech Mono var(--text-dim), `letter-spacing: 0.18em`
- Romanian day/month abbreviations: `[DUM,LUN,MAR,MIE,JOI,VIN,SÂM]`, `[IAN,FEB,MAR,APR,MAI,IUN,IUL,AUG,SEP,OCT,NOV,DEC]`

**Status badges (right):** flex row, 10px gap. Each badge:
- `padding: 5px 10px`, `min-width: 78px`
- `border: 1px solid var(--border-glass)`, `background: var(--bg-glass)`
- **Cut corner:** `clip-path: polygon(0 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%)`
- Two stacked lines: label (8px 600 Exo 2 dim, uppercase 0.18em) over value (11px Share Tech Mono primary)
- Variants by kind: `active` (cyan border + cyan light value), `ok` (green border + green value), `alert` (red), `dim` (default)
- Badges shown: `Voice / Agents / Memory / LM Studio`

### 2. Background layers

Three fixed `position: fixed; inset: 0; pointer-events: none` divs behind the UI:

- **`.hud-bg-grid`** (z-index 0): `background-image: radial-gradient(var(--accent-faint) 1px, transparent 1px); background-size: 28px 28px;` plus a soft center radial. Toggleable via Tweaks.
- **`.hud-bg-vignette`** (z-index 0): `radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.55) 80%, rgba(0,0,0,0.85) 100%)`
- **`.hud-scanline`** (z-index 1): `1px` tall horizontal line, gradient `transparent → var(--accent) → transparent`, `opacity: 0.18`, `box-shadow: 0 0 12px var(--accent)`, animated top: -1px → 100% over 7s linear infinite. Toggleable.

### 3. Bracket frame (`.bracket`)

The wrapper used for every panel/widget — a card with four corner brackets.

- `background: linear-gradient(180deg, rgba(7,17,31,0.7), rgba(7,17,31,0.4))`
- `border: 1px solid var(--border-glass)`
- `padding: var(--pad-panel)`
- 4 corner accents: `position: absolute`, `width/height: 10px`, `border-color: var(--accent)`, one border-side each (e.g. top-left has `border-top: 1px solid; border-left: 1px solid`)
- **Header (`.bk-head`):** optional. `display: flex; justify-content: space-between; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed var(--border-glass)`
  - `.bk-label` left, `.bk-status` right (Share Tech Mono var(--accent))

### 4. Agent list (left panel)

Wrapped in `<Bracket label="AGENT NETWORK" status="11/15">`.

- Grouped by tier: `CNS / BIZ / SEC / FND`. Each group header has a small `[CNS]`-style tag (10px mono, 1px var(--accent-dim) border, padding 1px 5px) + dim uppercase label.
- Each agent row: 5-column grid → `dot | name | model-badge` / `dot | role | role`
  - Default: status dot 8px, name (Exo 2 500 13px), role below (Share Tech Mono 9px var(--text-dim)), model badge top-right (`gemma-4` or `claude-haiku`, 9px mono in 1px box)
  - Hover: `background: var(--bg-glass)`
  - Active (`.is-active`): same bg + `border-left: 2px solid var(--accent)` + name in var(--accent-light) with `text-shadow: 0 0 10px var(--accent-glow)` + model badge border var(--accent-dim)

**Status dot states (universal):**
- `active` (green): 8px, `background: var(--green-active)`, `box-shadow: 0 0 6px var(--green-active)`, **pulses** via `@keyframes pulse-green` (2s ease-in-out infinite, scale 1→1.25→1 + shadow ring 0→4px→0)
- `ready` (cyan): static, 4px glow
- `idle`: muted `rgba(232,244,253,0.18)`
- `warn` (amber): 6px glow
- `alert` (red): 6px glow + faster pulse (1.2s)

### 5. System stats (bottom of left panel)

A second `<Bracket label="SYSTEM" status="NOMINAL">` below the agent list.

Rows in Share Tech Mono:
- HOST / CPU / BACKEND / MODEL / LATENCY / UPTIME — simple key/value rows
- **Meters** for RAM / VRAM / GPU LOAD:
  - Header line: `key` left + `used/total unit` right
  - Bar: 6px tall, `background: rgba(0,174,239,0.06)`, fill via `linear-gradient(90deg, var(--accent), var(--accent-light))` with `box-shadow: 0 0 6px var(--accent-glow)`
  - 10 tick marks overlaid as 1px dividers in `rgba(3,8,16,0.6)`

### 6. Voice visualizer (top of center panel)

Wrapped in `<Bracket label="VOICE HUD" status="LISTENING">`. Inner `.viz` is `min-height: 160px`, flex column centered, clickable to cycle states.

**Orbital rings (decoration):** three absolute-positioned circles behind the core, all dashed/solid borders var(--accent-dim/faint):
- ring-1: 140×140, dashed, opacity 0.4, rotates 360° over 40s
- ring-2: 200×200, solid, opacity 0.22, rotates reverse over 60s
- ring-3: 260×260, dashed, opacity 0.12, rotates over 90s
- Toggleable via Tweaks.

**Core states (4):**

| State        | Visual                                                                                             |
|--------------|----------------------------------------------------------------------------------------------------|
| `idle`       | 11 bars all 4px tall, opacity 0.35, no glow, no animation                                          |
| `listening`  | 11 bars animating via `@keyframes bar-dance` (1.1s, cubic-bezier(0.4,0,0.6,1)), stagger 80ms each. Keyframes: 0%→6px, 25%→38px, 50%→14px, 75%→48px, 100%→6px. Color var(--accent), `box-shadow: 0 0 6px var(--accent-glow)`. |
| `processing` | SVG hexagon (84×84), stroke 1.2px var(--accent), `drop-shadow(0 0 8px var(--accent-glow))`. Outer hex spins 360° over 2.4s. Inner hex (60% scale, opacity 0.6) spins reverse over 1.6s. Central + 3 cardinal dots filled. |
| `speaking`   | Bars taller (10→70px), faster (700ms cycle, 50ms stagger). `background: linear-gradient(180deg, var(--accent), var(--green-active))`. `box-shadow: 0 0 10px var(--accent), 0 0 6px var(--green-dim)`. |

**Readout (below core):**
- Status label, Share Tech Mono 11px, letter-spacing 0.18em, var(--accent-light), `text-shadow: 0 0 8px var(--accent-glow)`. Blinks on listening/processing via `@keyframes blink` (1.4s, opacity 1↔0.4).
- Label strings:
  - idle → `— STANDBY —`
  - listening → `[ LISTENING · WAKE WORD DETECTED ]`
  - processing → `[ PROCESSING · ROUTING TO SPECIALISTS ]`
  - speaking → `[ <AGENT_NAME> RESPONDING ]`
- Meta line below: `CH · VOICE · STT · WHISPER-LARGE-V3 · TTS · KOKORO-EN-GB-M1` separators in var(--accent-dim)

### 7. Conversation (`.convo`)

Wrapped in `<Bracket label="CONVERSATION · SESSION 20260527-0723" status="4 TURNS">`.

- `display: flex; flex-direction: column; gap: 14px; overflow-y: auto`
- Top/bottom fade mask: `mask-image: linear-gradient(180deg, transparent 0, #000 14px, #000 calc(100% - 14px), transparent 100%)`
- Custom scrollbar: 3px wide, thumb var(--accent-dim)
- Auto-scroll to bottom on new message via `useLayoutEffect` (or `el.scrollTop = el.scrollHeight` after DOM update)

**Message (`.msg`):**
- Entry animation `@keyframes msg-in`: 220ms, opacity 0→1 + translateY 8px→0

**User messages (`.msg-user`):**
- `align-items: flex-end`
- Meta row reversed: tag `[ANDREI]` first, timestamp pushed to the left edge
- Body: `padding: 12px 16px; max-width: 80%`; `background: color-mix(in oklch, var(--accent) 8%, transparent)`; `border: 1px solid var(--accent-dim)`; text color var(--accent-light)
- **Notched corner (bottom-left):** `clip-path: polygon(0 0, 100% 0, 100% 100%, 8px 100%, 0 calc(100% - 8px))`

**Agent messages (`.msg-agent`):**
- Meta: tag `[JARVIS]` (or active agent name uppercased, var(--accent), border var(--accent-dim)) + role (`Prime Orchestrator`, 9px dim) + timestamp right
- Body: `background: rgba(232,244,253,0.02)`; `border: 1px solid rgba(232,244,253,0.06)`
- **Notched corner (top-left):** `clip-path: polygon(0 8px, 8px 0, 100% 0, 100% 100%, 0 100%)`

**Thinking / orchestration trace** (shown while waiting for response):
- Replaces `.msg-body` with `.thinking-trace`
- Dashed border var(--accent-dim), bg var(--bg-glass), padding 10px 16px, max-width 80%
- 3 lines, each starting with `›` (var(--accent)):
  - `› classify intent ...` (3 pulsing dots: `@keyframes dot-pulse`, 1.2s, stagger 200ms, scale 1↔1.4 + opacity 0.2↔1)
  - `› route · Jarvis → Stark → Veronica` (agents as pills in var(--accent-light) with `→` separators)
  - `› synthesize ...`

### 8. Input bar (`.input-bar`)

Bottom of center panel, full width:
- `display: flex; align-items: center; gap: 8px; padding: 4px`
- `background: var(--bg-glass); border: 1px solid var(--border-glass)`
- `:focus-within` → border var(--accent), `box-shadow: 0 0 16px color-mix(in oklch, var(--accent) 18%, transparent)`

**Sections (left → right):**
1. **Prefix:** `›` (16px Share Tech Mono var(--accent), blinking 1s) + `CH:VOICE → JARVIS` (10px mono, var(--text-dim), letter-spacing 0.12em). Right-bordered with var(--border-glass), height 32px.
2. **Field:** transparent, no border, height 38px, Exo 2 14px, placeholder `Comandă... (text sau wake word „jarvis")` in var(--text-dim) italic
3. **Mic button** (38×38): SVG mic glyph. Default var(--text-dim). When active: var(--green-active), `text-shadow: 0 0 6px var(--green-active)`, pulses via `@keyframes pulse-mic` (1.4s color shift to var(--accent-light))
4. **Transmit button:** `TRANSMIT` text + arrow SVG, padding 0 16px, Share Tech Mono 10px 0.15em, color var(--accent). Hover: bg `color-mix(in oklch, var(--accent) 12%, transparent)`

### 9. Weather card (right panel, top)

`<Bracket label="AMBIENT · WEATHER" status="BUCUREȘTI">` with:
- **Main row:** big temp (42px Share Tech Mono var(--accent-light), `text-shadow: 0 0 14px var(--accent-glow)`) + unit (16px var(--accent-dim)). Weather icon (cloud/rain SVG, 36×28, stroke 1.5px var(--accent)) on the right.
- **Description:** 13px var(--text-secondary), e.g. `Înnorat cu deschideri`
- **2×2 stats grid:** VÂNT / UMID. / SIMTE / UPD. Keys in mono 10px dim, values right-aligned. Top + bottom dashed borders.
- **Forecast strip:** 5 cells, each `flex: 1`, background var(--bg-glass), padding 6px. Vertical stack: hour (10px mono dim) / icon (18px, accent) / temp (10px mono primary).

### 10. Calendar card

`<Bracket label="CALENDAR · ASTĂZI" status="NEXT 11:00">`.

- Rows: `grid-template-columns: 14px 44px 1fr; gap: 8px; padding: 8px 10px`
- States:
  - `past`: opacity 0.35, marker `○`
  - `next`: bg var(--bg-glass), `border-left: 2px solid var(--accent)`, marker `▸` in var(--accent)
  - `upcoming`: default, marker `·` in var(--text-dim)
- Marker mono. Time 12px Share Tech Mono var(--accent-light). Title 13px Exo 2 primary. Owner 9px mono dim (`via Pepper`).

### 11. Agents grid

`<Bracket label="AGENT GRID" status="11/15 ONLINE">`.

- 5-column × 3-row grid (15 cells), `gap: 6px`
- Each cell: `aspect-ratio: 1`, `background: var(--bg-glass)`, `border: 1px solid var(--border-glass)`
- Contents: status dot (8px) over 3-letter tag (`JAR`, `FRI`, `PEP`, etc.) in 9px mono var(--text-secondary)
- States mirror status dot colors. Active cell: `border-color: var(--accent)`, `box-shadow: 0 0 10px var(--accent-glow), inset 0 0 8px var(--accent-faint)`, tag in var(--accent-light)
- **Legend below grid:** flex row, 9px mono, 3 entries: `active / ready / idle` with mini dots. Dashed top border.

### 12. Heartbeat alerts feed

`<Bracket label="HEARTBEAT · ALERTS" status="3 ACTIVE">`.

- List of `.hb` rows: `grid-template-columns: 3px 1fr; gap: 10px; padding: 8px 10px; background: var(--bg-glass); border: 1px solid var(--border-glass)`
- Severity bar (3px wide, full row height) on the left, color by level:
  - `info` → var(--accent)
  - `ok` → var(--green-active)
  - `warn` → var(--amber-warn)
  - `alert` → var(--red-alert)
- Head: agent tag (`[FRIDAY]`, colored to match severity) + timestamp right (10px mono dim)
- Body: 12px Exo 2 primary

---

## State & interactions

```js
// State (replace mock data.js with real fetches)
const state = {
  activeAgent: 'jarvis',         // selected in left panel; affects [TAG] in chat
  voiceState:  'idle',           // 'idle' | 'listening' | 'processing' | 'speaking'
  agents:      [],               // GET /agents
  messages:    [],               // accumulated chat turns
  thinking:    null,             // agent id currently orchestrating (shows trace)
  routedAgents: [],              // [agentId, ...] for trace pills
  weather:     null,             // from /dashboard
  calendar:    [],               // mock for now — no calendar API exists
  notifications: [],             // from /ws heartbeat_alert events
  sys:         {},               // from /status
};
```

**Submit flow:**
1. User presses Enter or Transmit → append `{ role: 'user', text, ts }` to messages
2. Set `voiceState: 'processing'`, `thinking: 'jarvis'`, `routedAgents: ['jarvis', activeAgent]`
3. POST `/chat/stream` with `{ message }` — read SSE chunks, accumulate `token`s
4. On first token: set `voiceState: 'speaking'`, clear `thinking`, start appending an agent message
5. On `done`: keep the final message, set `voiceState: 'idle'` after 1.4s timeout

**Voice state cycling:** Clicking the voice visualizer cycles `idle → listening → processing → speaking → idle` (for demo/testing). In production, the state is driven by `/ws` events:
- `voice_state_change: { state: 'listening' }` → set voiceState
- `heartbeat_alert: { agent_id, message, level }` → prepend to notifications
- `agent_status_change: { agent_id, status }` → mutate agents[].status
- `proactive_message: { agent_id, text }` → append to messages

**Polling fallback (if no WebSocket yet):** `setInterval(refreshDashboard, 30_000)` to `GET /dashboard` for weather/news/system data.

---

## Animations & keyframes (exact)

```css
@keyframes spin           { to { transform: rotate(360deg); } }
@keyframes ring-rot       { to { transform: rotate(360deg); } }
@keyframes hex-spin       { to { transform: rotate(360deg); } }
@keyframes hex-spin-rev   { to { transform: rotate(-360deg); } }
@keyframes scanline       { 0% { top: -1px; } 100% { top: 100%; } }
@keyframes blink          { 50% { opacity: 0.4; } }
@keyframes msg-in         { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes pulse-green    {
  0%, 100% { transform: scale(1);    box-shadow: 0 0 0 0   rgba(57,255,139,0.5); }
  50%      { transform: scale(1.25); box-shadow: 0 0 0 4px rgba(57,255,139,0);   }
}
@keyframes pulse-red {
  0%, 100% { transform: scale(1);   box-shadow: 0 0 4px  var(--red-alert); }
  50%      { transform: scale(1.2); box-shadow: 0 0 10px var(--red-alert); }
}
@keyframes bar-dance {
  0%, 100% { height: 6px;  }
  25%      { height: 38px; }
  50%      { height: 14px; }
  75%      { height: 48px; }
}
@keyframes bar-speak {
  0%, 100% { height: 10px; }
  30%      { height: 60px; }
  60%      { height: 24px; }
  80%      { height: 70px; }
}
@keyframes dot-pulse {
  0%, 100% { opacity: 0.2; transform: scale(1);   }
  50%      { opacity: 1;   transform: scale(1.4); }
}
```

---

## Agents data (mirrors `agents.yaml`)

Tiers used in the UI (renamed for short HUD labels):
- `CNS` (Command — Nervous System): jarvis, friday, pepper, jerome
- `BIZ` (Business Intelligence): athena, stark, veronica, vision
- `SEC` (Security & Infrastructure): steve, oracle, ultron
- `FND` (Foundation): gecko, hercules, hephaestus, frigga

Backend should return agents in this order with a `tier: 'CNS'|'BIZ'|'SEC'|'FND'` field. Currently the YAML uses `command/business/tech/foundation` — map them in the response (or update the YAML to match).

---

## Tweaks (optional in production)

The prototype includes a floating Tweaks panel for live experimentation. **You can keep or drop this in production** — it's not a user-facing feature, just a dev convenience. Controls:
- Accent color: 4 swatches → flips `--accent` and `--accent-light` on `<html>`
- Voice state: dropdown to force any of the 4 states (useful for testing)
- Toggles: dot grid backdrop / scan line / orbital rings on/off
- Density: compact / regular / comfy → flips `--pad-panel` and `--gap-panel`

If you keep it, expose it under a `?dev=1` query param or behind a keyboard shortcut.

---

## Assets

- **Fonts:** Exo 2 + Share Tech Mono (Google Fonts CDN, link tag in `<head>`)
- **Icons:** all inline SVG (mic, send arrow, weather cloud/rain, hexagon, arc-reactor mark) — no icon library required
- **No images** in the design

---

## Files in this bundle

```
design/
├── index.html        — full prototype shell + all CSS
├── app.jsx           — root React component, state, simulated orchestration
├── components.jsx    — TopBar, AgentList, VoiceVisualizer, Conversation, ambient widgets
├── data.js           — mock agents/messages/weather/calendar/notifications
└── tweaks-panel.jsx  — Tweaks shell (drop in production if you don't keep tweaks)
```

Open `design/index.html` in a browser to see the prototype running. All four voice states + accent variants are toggleable from the Tweaks panel (bottom-right).

---

## Implementation checklist for Claude Code

1. [ ] Wire fonts in `cabinet/agents/web/templates/index.html` `<head>`
2. [ ] Move CSS from prototype `<style>` block → `static/style.css`. Keep all CSS custom properties identical.
3. [ ] Port `components.jsx` + `app.jsx` → `static/app.js` (vanilla JS or keep React via CDN). Replace `JARVIS_DATA` with live fetches.
4. [ ] Rebuild the page DOM at startup matching the prototype structure (TopBar / left panel / center panel / right panel).
5. [ ] Wire `GET /status` → header status badges + agent list
6. [ ] Wire `GET /dashboard` → weather + sys panel (poll every 30s)
7. [ ] Wire `POST /chat/stream` → conversation flow with token streaming and the orchestration trace
8. [ ] (Stretch) Add WebSocket endpoint `/ws` to `web.py` for live voice state, heartbeat alerts, agent status pushes
9. [ ] Calendar card — currently mock. Either keep mock until a calendar plugin lands, or add a `/calendar` endpoint backed by the Pepper agent's google-calendar plugin.
10. [ ] Test all four voice states render correctly by manually setting state from the JS console
11. [ ] Test responsive breakpoints at 1280 / 1024 px widths
12. [ ] (Optional) Keep the Tweaks panel behind `?dev=1`
