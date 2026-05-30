# Jarvis Hub — Implementation Handoff for opencode (big-pickle)

> **Read this whole file first.** Then open `design/index.html` in a browser to see the working prototype before touching code. Every visual / interaction in the prototype is the target — match it.

---

## 1 · What you're building

A **redesign of the existing Jarvis Hub web UI** (Andrei's local-first 15-agent AI orchestration system). The current page at `cabinet/agents/web/index.html` is a plain chat box. The new design replaces it with a **3-column "live HUD"**: agent network on the left, a neural-network visualizer + chat in the center, ambient widgets on the right.

**Aesthetic target:** *"Bloomberg Terminal as Apple would have designed it in 2035."* Dark, geometric, technical, calm — translucent panels, hairline cyan accents, monospaced numbers, restrained motion. Original interface design throughout, no recreation of any branded UI.

**Stack constraint:** the project is **Python 3.12 + aiohttp**, no bundler, no Node toolchain. JS must run as plain `<script>` or `<script type="module">` files served by aiohttp. **No npm build step.**

---

## 2 · Tech context (existing project)

```
cabinet/
├── agents/
│   ├── _system/agents.yaml      ← 15 agents in 4 tiers (CNS/BIZ/SEC/FND)
│   ├── jarvis/SOUL.md           ← per-agent identity + heartbeat config
│   ├── friday/, pepper/, ...    ← all 15
│   └── web.py                   ← aiohttp app, serves /, /chat/stream, /status, /dashboard
└── (the new UI lives under agents/web/templates + agents/web/static)
```

**Backend already serves these (do NOT change endpoint shapes):**

| Method | Path             | Returns                                       |
|--------|------------------|-----------------------------------------------|
| GET    | `/`              | HTML page (this is what you're replacing)     |
| GET    | `/status`        | `{ llm_backend, agents: [{id,name,status,...}] }` |
| GET    | `/agents`        | `[{...}]` — agent list                         |
| GET    | `/dashboard`     | `{ weather, news, system, conversation }`     |
| POST   | `/chat`          | `{ message }` → `{ response, agent }`         |
| POST   | `/chat/stream`   | SSE — `data: {token}` then `data: {done:true}` |
| GET    | `/memory`, `/sessions`, `/learning`, `/security`, `/bench` | diagnostics |

**Not yet implemented — you may need to add:**
- `GET /tasks` — list of `{id, owner, project, label, state, progress}` for the network visualizer's task fan. (Stub with mock data if not ready — see `data.js` for the shape.)
- `GET /ticker` — list of `{agent, verb, obj, pct, pri}` for the situation ribbon (or compute from agent activity).
- `WS /ws` — push events for live updates (see §10). **Fallback to polling** if you can't add WebSocket in this pass.

LLM backend is **LM Studio on port 1234**, model `google/gemma-4-26b-a4b`. Some agents (Athena, Veronica, Vision) use `claude-haiku` for reasoning-heavy work.

---

## 3 · Output file layout

Target the existing project structure:

```
cabinet/agents/web/
├── templates/
│   └── index.html         ← page shell + Google Fonts link + <div id="root">
└── static/
    ├── style.css          ← every CSS rule from prototype <style> block
    ├── data.js            ← live-data adapter (replaces prototype's mock data.js)
    ├── app.js             ← root app, state, event wiring
    ├── components.js      ← TopBar, AgentList, Conversation, ambient cards
    ├── network.js         ← neural-network SVG visualizer
    └── enhancements.js    ← SituationTicker + CommandPalette + useLiveSys + useHotkey
```

**Two implementation modes — pick one:**

### Mode A (recommended): keep React via CDN, port `.jsx` → `.js`
The prototype uses React 18 via CDN + Babel-in-browser. For production, **drop Babel** (compile-time cost on every load) but **keep React from the same unpkg URLs** with the pinned integrity hashes from the prototype. Convert `.jsx` to `.js` by replacing JSX with `React.createElement(...)` calls. Most components are short — the conversion is mechanical. State and lifecycle stay identical.

```html
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js" crossorigin></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js" crossorigin></script>
<script src="static/data.js"></script>
<script src="static/components.js"></script>
<script src="static/network.js"></script>
<script src="static/enhancements.js"></script>
<script src="static/app.js"></script>
```

### Mode B: vanilla JS, no React
Render each component as a function returning a DOM tree (via `document.createElement` or template strings + `innerHTML`). Re-render the relevant subtree when state changes. Doable since state is shallow, but more code than Mode A.

Pick **A** unless you have a strong reason otherwise.

---

## 4 · Fidelity bar

**High-fidelity.** Match the prototype pixel-for-pixel. Every color, font size, animation timing, easing curve, padding value, border style is final. The prototype IS the design spec.

The prototype's CSS uses CSS custom properties for theming and lots of `color-mix(in oklch, ...)` — both are widely supported, keep as-is.

---

## 5 · Design tokens

```css
:root {
  /* Backgrounds */
  --bg-void:        #030810;   /* page bg */
  --bg-surface:     #07111f;   /* card surface */
  --bg-glass:       rgba(0, 174, 239, 0.04);
  --border-glass:   rgba(0, 174, 239, 0.12);
  --border-active:  rgba(0, 174, 239, 0.35);

  /* Accent — user-switchable; default cyan */
  --accent:         #00AEEF;
  --accent-light:   #7FDBFF;
  --accent-dim:     rgba(0, 174, 239, 0.4);
  --accent-faint:   rgba(0, 174, 239, 0.1);
  --accent-glow:    rgba(0, 174, 239, 0.35);

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
  --pad-panel:      16px;
  --gap-panel:      14px;
}
```

**Alternative accent palettes** (cycled via Tweaks panel, optional in production):

| Theme  | --accent  | --accent-light |
|--------|-----------|----------------|
| Cyan   | `#00AEEF` | `#7FDBFF`      |
| Amber  | `#FFB23F` | `#FFD787`      |
| Green  | `#39FF8B` | `#9CFFD2`      |
| Violet | `#9B6BFF` | `#D0B6FF`      |

**Fonts (via Google Fonts):**
```html
<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@200;300;400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
```

---

## 6 · Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  TOPBAR  (logo · clock · status badges)                ~78px         │
├──────────────────────────────────────────────────────────────────────┤
│  SITUATION TICKER  ● LIVE  ◀ marquee of agent activity ▶  32px       │
├──────────────┬─────────────────────────────────────┬─────────────────┤
│  AGENT LIST  │  NEURAL NETWORK VISUALIZER          │  WEATHER        │
│              │     (clamp 220–320px tall)          │  CALENDAR       │
│  280px       │                                     │  AGENTS GRID    │
│              ├─────────────────────────────────────┤  HEARTBEAT      │
│  ──────      │  CONVERSATION  (flex, scrolls)      │                 │
│  SYS STATS   │                                     │  320px          │
│              ├─────────────────────────────────────┤                 │
│              │  INPUT BAR     (fixed ~48px)        │                 │
└──────────────┴─────────────────────────────────────┴─────────────────┘
```

- `body` → `display:flex; flex-direction:column; height:100vh; overflow:hidden`
- `.hud-main` → `display:grid; grid-template-columns:280px 1fr 320px; gap:14px; padding:14px; flex:1; min-height:0`
- Each panel: `display:flex; flex-direction:column; gap:14px; min-height:0`
- Left/right panels: `overflow-y:auto`

**Responsive breakpoints** (keep these):
- `≤1280px` → side panels 240px / 280px, clock 36px
- `≤1024px` → side panels 200px / 240px, agent items hide model badge

---

## 7 · Components — detailed contract

The prototype is the source of truth. Refer to `design/components.jsx`, `design/network.jsx`, `design/enhancements.jsx`. Below is a feature-by-feature spec; cross-check values against the prototype CSS in `design/index.html`.

### 7.1 TopBar
- 3-col grid `1fr auto 1fr`, `padding:14px 24px`, `border-bottom:1px solid var(--border-glass)`, `backdrop-filter:blur(8px)`
- **Logo (left):** rotating 22×22 arc-reactor SVG (3 concentric circles + 4 cardinal ticks, `animation:spin 60s linear infinite`), stacked `JARVIS·HUB` (Exo 2 700, 17px, 0.18em) over `v0.2.1 · BONOBO-WS` (Share Tech Mono 10px, dim)
- **Clock (center):** live `HH:MM:SS` in Share Tech Mono 44px var(--accent), `text-shadow:0 0 18px var(--accent-glow)`, `font-variant-numeric:tabular-nums`. Below: localized RO date `LUN · 27 MAI 2026 · EUROPE/BUCURESTI` (mono 10px, 0.18em, dim). Use RO day/month abbreviations `[DUM,LUN,MAR,MIE,JOI,VIN,SÂM]` `[IAN,FEB,…,DEC]`.
- **Status badges (right):** 4 badges with `clip-path:polygon(0 0,100% 0,100% calc(100%-6px),calc(100%-6px) 100%,0 100%)`, stacked label (8px 600 dim) over value (mono 11px). Kinds: `Voice / Agents / Memory / LM Studio`. Color variants `active|ok|alert|dim`.

### 7.2 Situation Ticker (NEW — `enhancements.jsx`)
- Sits **under the topbar**, full width, 32px tall, `border-bottom:1px solid var(--border-glass)`
- **Head (200px, left):** pulsing red 7px dot + `LIVE` (mono 10px red, 0.18em) + `SITUATION · {voiceState}` (mono 9px dim, right-aligned)
- **Marquee (right):** items horizontally scrolling left at `64s linear infinite` via `transform:translateX(-50%)`. **Duplicate the items array** to make the loop seamless.
- Each item: agent glyph (14×14 SVG inline) + agent name (mono 10px var(--accent-light), 0.08em) + verb (italic) + obj + optional pct bar (36×3px) + separator `·`
- Severity colors (`hi|mid|warn|ok`) tint the agent name/glyph.
- Mask the marquee edges: `mask-image:linear-gradient(90deg,transparent 0,#000 24px,#000 calc(100%-24px),transparent 100%)`

### 7.3 Agent List (left panel)
Wrapped in `<Bracket label="AGENT NETWORK" status="11/15">`.
- Grouped by tier (CNS / BIZ / SEC / FND). Each group head: `[CNS]` tag (mono 10px, 1px accent-dim border) + uppercase label (Exo 2 9px 600, dim).
- Each row: 3-col grid `dot | name | model-badge` with role on second row. Hover bg `var(--bg-glass)`. Active: `border-left:2px solid var(--accent)`, name in `var(--accent-light)` with `text-shadow:0 0 10px var(--accent-glow)`.
- **Agent glyph** (NEW): each agent has a small 14×14 geometric SVG mark, rendered next to the status dot. See `data.js` `GLYPHS` map for paths. Color follows status.

### 7.4 System stats (bottom of left panel)
Second `<Bracket label="SYSTEM" status="NOMINAL">`.
- Rows: HOST / CPU / BACKEND / MODEL / LATENCY / UPTIME (mono 11px, key in dim 0.1em, value primary, MODEL value in accent)
- **Meters** for RAM / VRAM / GPU LOAD: 6px-tall bar with gradient fill + `box-shadow:0 0 6px var(--accent-glow)` + 10 tick marks overlay
- **Live values (NEW):** drive these from `useLiveSys(baseSys)` so they oscillate gently every 1.4s (sine + small noise). Static numbers feel dead.

### 7.5 Neural Network Visualizer (center, top)
Replaces the old "voice waveform" idea entirely. This is the heart of the redesign — read `design/network.jsx` carefully.

**Layout:**
- Central **JARVIS core** node (radial gradient, 30px radius, "JARVIS · CORE · v0.2.1" labels)
- 4 **tier hubs** at compass points (CNS top, BIZ right, SEC bottom, FND left), each a small hex with the tier id
- 15 **agent nodes** placed on a ring (~165px radius), grouped within their tier sector. Each is a hex with the agent's glyph inside + name label radially outside.
- Tasks fan out beyond each agent on small arcs (~250px radius); show as small dots colored by state (`running` cyan-light glow, `done` green dim, `queued` outline, `waiting` amber).

**Edges:**
- core → each agent (always; brighter on active route)
- agent → each of its tasks (brighter for running)
- **agent ↔ agent collab edges (NEW):** curved Bézier paths between agent pairs defined in `data.js` `COLLAB`. Use `M(ax,ay) Q(cx,cy) (bx,by)` where the control point is pulled 55% toward the center. Render with `stroke-width:0.6; stroke-dasharray:1 3; opacity:0.5`.

**Pulses (animated packets traveling along edges):**
- Core → active agents (one pulse per `status:'active'` agent, staggered)
- Agent → running tasks
- **Collab packets (NEW):** one or two `<animateMotion>` circles per collab edge depending on `dir` (`a-b | b-a | both`). Duration `4.5 - intensity*2.0` seconds.

**Interactions:**
- **Click** an agent node → make it the active agent (drives chat tag + conversation reply)
- **Double-click** an agent node → **focus mode** (NEW):
  - Bracket header switches to `NEURAL NETWORK · FOCUS · {AGENT}`
  - Other agents drop to 18% opacity, pointer-events off
  - Focused agent's hex enlarges to r=18, glyph displays at full scale
  - Its tasks expand into a **fan** (~99° spread, ~100px from the agent) with readable labels (`Q2 KPI deck · running`, `Churn forecast · running`, etc.)
  - Running task dots have an `animation:pulse-ring` (expanding ring out to r=14)
  - Esc or another double-click exits focus mode
- **Hover** → tooltip with role + active task list

### 7.6 Conversation
`<Bracket label="CONVERSATION · SESSION 20260527-0723" status="N TURNS">`.
- Auto-scroll bottom on new message
- Top/bottom fade mask
- User msg: right-aligned, cyan-tinted bg, `clip-path` notch on bottom-left corner
- Agent msg: left-aligned, `[JARVIS]`-style mono tag in accent + role + timestamp; body has notch on top-left corner
- **Thinking trace** (during streaming): 3 dashed lines (`› classify intent` / `› route · Jarvis → Stark → Veronica` (pills) / `› synthesize`) with pulsing dots animation

### 7.7 Input bar
- Prefix `›` (blinking) + `CH:VOICE → JARVIS` channel indicator
- Field (placeholder: `Comandă... (text sau wake word „jarvis")`)
- Mic toggle (pulses green when active)
- TRANSMIT button (mono 10px 0.15em + arrow SVG)
- Focus-within: border `var(--accent)`, `box-shadow:0 0 16px ...`

### 7.8 Right panel widgets

**Weather card** — temp (Share Tech Mono 42px accent-light + glow) + cloud/rain SVG + 2×2 stats grid + 5-hour forecast strip
**Calendar card** — rows with marker `○|▸|·`, time (mono cyan-light) + title + `via {agent}`. States: past (opacity 0.35) / next (bg + left-accent border) / upcoming
**Agents grid** — 5×3 cells with status dots + 3-letter tags, hover/active states, legend
**Heartbeat feed** — list with severity bar (left side, 3px wide), agent tag, timestamp, text. Levels: info / ok / warn / alert

### 7.9 Command Palette (NEW — Cmd+K / Ctrl+K)
Lives in `enhancements.jsx`.
- **Hotkey:** Cmd+K (Mac) or Ctrl+K (others) — bind to `window keydown`, preventDefault, toggle open
- **Layout:** centered overlay, `width: min(640px, 92vw)`, padded `18vh` from top, fade+pop animation (`pal-fade` + `pal-pop` keyframes from prototype)
- Backdrop: `rgba(3,8,16,0.7)` + `backdrop-filter:blur(6px)`, click outside to close
- 4 corner brackets like other panels
- **Head:** `›` prompt + search input + hint text `↑↓ navigate · ↵ run · esc close`
- **Body:** ranked results list, max 14 entries
- **Foot:** `JARVIS HUB · n matches · ⌘K`
- **Search corpus:** agents + tasks + projects + commands (voice state shortcuts, clear-focus)
- **Ranking:** substring match in `tags` (boost 10), label-prefix (8), label-includes (4), agent kind +1
- **Keyboard:** ↑↓ to navigate selection, Enter to run, Esc to close, Mouse hover sets selection
- **Actions emitted via `onAction(action, item)`:**
  - `{type:'focus_agent', agent:'stark'}` → setActiveAgent
  - `{type:'voice_state', value:'listening'}` → setTweak('voiceState', value)
  - `{type:'clear_focus'}` → setFocusAgent(null)
  - `{type:'filter_project', project:'Digitaholic'}` → (your call — filter network or right panel)

---

## 8 · Agent glyphs (NEW)

Each agent has a small geometric SVG glyph. **Paths are defined in `data.js` `GLYPHS`** — copy them as-is. Used in:
- Agent list rows
- Network nodes (inside hex)
- Situation ticker rows
- Command palette results

Rendering pattern:
```html
<svg viewBox="-12 -12 24 24" width="14" height="14">
  <path d={glyph} fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
</svg>
```

Color is inherited from `currentColor` — set on the parent.

---

## 9 · Animations & keyframes (must match exactly)

All defined in `design/index.html`'s `<style>`. The important ones:

```css
@keyframes spin           { to { transform: rotate(360deg); } }
@keyframes ring-rot       { to { transform: rotate(360deg); } }
@keyframes hex-spin       { to { transform: rotate(360deg); } }
@keyframes hex-spin-rev   { to { transform: rotate(-360deg); } }
@keyframes scanline       { 0% { top: -1px; } 100% { top: 100%; } }
@keyframes blink          { 50% { opacity: 0.4; } }
@keyframes msg-in         { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes pulse-green    { 0%,100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(57,255,139,0.5); }
                            50% { transform: scale(1.25); box-shadow: 0 0 0 4px rgba(57,255,139,0); } }
@keyframes pulse-red      { ... }
@keyframes pulse-mic      { 50% { color: var(--accent-light); } }
@keyframes dot-pulse      { 0%,100% { opacity: 0.2; transform: scale(1); }
                            50% { opacity: 1; transform: scale(1.4); } }
@keyframes ticker-roll    { 0% { transform: translateX(0); }
                            100% { transform: translateX(-50%); } }
@keyframes pulse-ring     { 0% { r: 6; opacity: 0.8; }
                            100% { r: 14; opacity: 0; } }
@keyframes pal-fade       { from { opacity: 0; } to { opacity: 1; } }
@keyframes pal-pop        { from { transform: translateY(-12px) scale(0.96); opacity: 0; }
                            to { transform: none; opacity: 1; } }
```

The network has additional packet motion via SVG `<animateMotion>` (not CSS) — see `network.jsx`.

---

## 10 · State & live data

```js
const state = {
  activeAgent:   'jarvis',         // selected agent
  focusAgent:    null,             // dbl-clicked agent (focus mode in network)
  voiceState:    'idle',           // idle | listening | processing | speaking
  paletteOpen:   false,            // Cmd+K
  agents:        [],               // GET /agents or /status
  tasks:         [],               // GET /tasks  (NEW endpoint)
  collab:        [],               // statically defined for now (data.js COLLAB)
  ticker:        [],               // GET /ticker (NEW) — or compute from tasks
  messages:      [],               // chat turns
  thinking:      null,             // agent id currently orchestrating
  routedAgents:  [],               // for the orchestration trace pills + network packets
  sys:           {},               // GET /status — pumped through useLiveSys() for oscillation
  weather:       null,             // GET /dashboard
  calendar:      [],               // mock for now; back with calendar plugin later
  notifications: [],               // from WS heartbeat_alert
};
```

**WebSocket events (when you add `/ws`):**
- `voice_state_change: { state: 'listening' }` → `state.voiceState`
- `agent_status_change: { agent_id, status }` → mutate `state.agents`
- `task_update: { task_id, state, progress }` → mutate `state.tasks`
- `heartbeat_alert: { agent_id, message, level }` → unshift into `state.notifications`
- `proactive_message: { agent_id, text }` → append to `state.messages` + flash on the network

**Polling fallback** (if WS not ready): `setInterval(refreshAll, 30_000)` calling `/status` + `/dashboard` + `/tasks`.

**Submit flow** (when user presses Enter or TRANSMIT):
1. Append user msg `{role:'user', text, ts}` → `state.messages`
2. `voiceState = 'processing'`, `thinking = 'jarvis'`, `routedAgents = ['jarvis', activeAgent]` (or computed from intent)
3. POST `/chat/stream` with `{message}`. Read SSE — for each `token` append to a buffer; on first token: `voiceState = 'speaking'`, `thinking = null`, start appending a new agent message turn
4. On `{done:true}`: keep final message. After 1400ms: `voiceState = 'idle'`, `routedAgents = []`

---

## 11 · Tier mapping

The UI uses short tier codes; backend YAML uses long names. **Map at the boundary:**

```python
TIER_MAP = {
  'command': 'CNS',
  'business': 'BIZ',
  'tech': 'SEC',
  'foundation': 'FND',
}
```

CNS (Command — Nervous System): jarvis, friday, pepper, jerome
BIZ (Business Intelligence): athena, stark, veronica, vision
SEC (Security & Infrastructure): steve, oracle, ultron
FND (Foundation): gecko, hercules, hephaestus, frigga

---

## 12 · Tweaks panel (optional in production)

The prototype includes a floating dev panel at bottom-right. Controls:
- Accent color (4 swatches)
- Voice state forced override
- Toggles: dot-grid backdrop / scan line / orbital rings
- Density: compact / regular / comfy

**In production:** put this behind `?dev=1` query param OR drop it entirely. Don't ship the panel to end users without gating.

---

## 13 · Implementation checklist for opencode

Work in this order. Verify each step in a browser before moving on.

1. [ ] Create directory structure under `cabinet/agents/web/{templates,static}/`
2. [ ] Wire Google Fonts + React (production CDN, no Babel) in `templates/index.html`
3. [ ] Copy the entire prototype `<style>` block → `static/style.css`. Don't omit anything — every rule is intentional.
4. [ ] Convert `design/data.js` → `static/data.js`, but replace the IIFE-mock with an async `loadJarvisData()` that fetches `/status`, `/dashboard`, `/tasks` and assembles the same shape on `window.JARVIS_DATA`. Keep the static lookup tables (`GLYPHS`, `PROJECTS`, `COLLAB`, `TIERS`, `TICKER` defaults) inline.
5. [ ] Port `components.jsx` → `components.js` (JSX → `React.createElement`). Verify TopBar, AgentList (with glyphs!), Conversation, InputBar, Weather/Calendar/AgentsGrid/HeartbeatFeed all render.
6. [ ] Port `network.jsx` → `network.js`. **This is the longest file** — take it carefully. Verify:
   - All 15 agent nodes appear with hex outline + glyph + status color
   - Core → agent edges render
   - Collab Bézier curves render with traveling packets
   - Click changes activeAgent (chat tag updates)
   - Double-click enters focus mode (others dim, task fan appears)
   - Esc exits focus mode
7. [ ] Port `enhancements.jsx` → `enhancements.js`. Verify:
   - SituationTicker scrolls smoothly (no jump at the loop point — that's why we duplicate the array)
   - Cmd+K (and Ctrl+K) opens the palette
   - Typing filters results
   - ↑↓/Enter/Esc keyboard navigation
   - `useLiveSys` oscillates RAM/VRAM/GPU/latency every 1.4s
8. [ ] Port `app.jsx` → `app.js`. Wire all state, hotkeys, submit flow.
9. [ ] **Wire to real endpoints** — replace any remaining mock fetches with the actual `/status`, `/chat/stream`, etc.
10. [ ] Add `GET /tasks` endpoint to `web.py` (return `[]` for now if no real data, but it should respect the shape).
11. [ ] **(Stretch)** Add `WS /ws` endpoint pushing the 4 event types in §10.
12. [ ] Test responsive: 1280px and 1024px breakpoints
13. [ ] Test all 4 voice states render via Tweaks panel
14. [ ] Test focus mode for at least 3 agents (Stark, Hephaestus, Pepper) — confirm task fan labels are legible and packets animate
15. [ ] Open Cmd+K, search "cosmina" — should surface Hephaestus's "Cosmina" project. Search "deploy" — Steve's task. Search "voice" — the voice-state commands.
16. [ ] Sanity-check the situation ticker has at least 8 items and scrolls smoothly.

---

## 14 · Common pitfalls

- **Don't ship Babel-in-browser** — drop it for production. JSX → `React.createElement` is a one-time conversion.
- **Don't change the design tokens** without explicit approval. They're tuned for the HUD feel.
- **Don't reduce the network's spacing** — agent labels need their radial space or they collide.
- **Don't auto-scroll the conversation on every render** — only when the message list length changes (use `useLayoutEffect` with `messages.length` as dep).
- **Don't poll faster than 30s** — the LM Studio backend is local and small queries are cheap, but the WS path is the right one.
- **Romanian copy** — keep all Romanian strings as-is (`Comandă...`, day/month abbreviations, etc.). Don't translate.
- **Glyphs render via `currentColor`** — if a glyph appears black or invisible, you forgot to set a `color` on its parent.

---

## 15 · Files included in this bundle

```
design/
├── index.html         — full prototype (all CSS in one <style> block)
├── app.jsx            — root component, state, submit flow, hotkeys
├── components.jsx     — TopBar, AgentList, Conversation, ambient cards
├── network.jsx        — neural-network SVG visualizer
├── enhancements.jsx   — SituationTicker, CommandPalette, useLiveSys, useHotkey
├── data.js            — agents, tasks, projects, collab edges, ticker items, glyphs
└── tweaks-panel.jsx   — dev tweaks shell (drop or gate behind ?dev=1)
```

Open `design/index.html` directly in a browser — it works offline once Google Fonts + React CDN load. Click around, press Cmd+K, double-click an agent. That's the target.

---

## 16 · Acceptance criteria

Done = a freshly-cloned Jarvis project, after starting the aiohttp server, shows:
- The new HUD at `http://localhost:8000/` (or whatever port `web.py` uses)
- All 15 agents in the left panel with correct tier grouping + glyphs
- Live network with at least one running pulse on the active agents + collab edges visible
- Working chat → real LM Studio responses → routed through the orchestration trace
- Situation ticker scrolling
- Cmd+K opens, filters, runs commands
- Focus mode on dbl-click works
- Live clock + (lightly) oscillating sys metrics
- Zero console errors
- Matches the prototype within ~5% on color/spacing/typography
