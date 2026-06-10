# PR: HUD v2 — design prototype + handoff (review & implement)

**Branch suggestion:** `feat/hud-v2-prototype`
**Type:** Design prototype + implementation handoff. **Not production code yet** — this PR exists so Claude Code (Opus) can review with full context, find bugs/gaps, and implement the production version.

---

## What this PR adds

A complete, interactive **HUD v2 design prototype** and the docs that drive its implementation. All four design decisions (D1–D4) from `docs/design/HUD_V2_BRIEF.md` are now **locked** (owner-approved — see below).

```
hud-v2/                         # the prototype (React-via-Babel, no build step)
  hud-v2.html                   # entry — loads fonts, CSS, then modules in order
  v2-style.css                  # ENTIRE design system as CSS vars + classes (source of truth)
  v2-data.jsx                   # all data on window.V2 (mock — replace with live adapter)
  v2-primitives.jsx             # icons, Glyph, Reactor, Meter, hooks, formatters
  v2-network.jsx                # NetworkBrain hero (focus mode, packets, collab edges)
  v2-cockpit.jsx                # Conversation, CognitionStream + buildTrace, InputBar
  v2-modes.jsx                  # AgentsMode + Dossier, TrustMode, MemoryMode
  v2-modes2.jsx                 # AutonomyMode, BuildMode, ObserveMode, InteropMode
  v2-modes3.jsx                 # ChatMode (focus), CommsMode, AdminMode
  v2-modes4.jsx                 # FinanceMode, HealthMode, KnowledgeMode, FamilyMode
  v2-shell.jsx                  # TopBar, Ticker, Rail/Tabs, columns, Palette (⌘K), Ambient
  v2-app.jsx                    # root state, hotkeys, submit→cognition flow, mount
  tweaks-panel.jsx              # design-tool tweak panel (PROTOTYPE ONLY — drop in prod)
docs/design/
  HUD_V2_HANDOFF.md             # ★ read first — architecture, data contract, build plan, gotchas
  HUD_V2_NAVIGATION_MAP.md      # map of all 15 modes → component → data key → hotkey
  hud-v2-decisions.html         # D1–D4 sign-off page (all four locked)
```

> Placement is a suggestion — integrate where the repo keeps front-end. The handoff doc explains the migration to the approved stack.

---

## Decisions locked (owner-approved)

| | Decision | Outcome |
|---|---|---|
| **D1** | Information architecture | **Left rail of modes + ⌘K** (tabs available as a live toggle) |
| **D2** | Build stack | **Vite + React + TypeScript**, bundled, self-hosted fonts |
| **D3** | HUD / Admin unification | **Unify** — Admin built as a mode in the v2 shell (`v2-modes3.jsx`) |
| **D4** | v1 scope | All **15 modes** built at fidelity: Cockpit · Chat · Agents · Trust · Memory · Autonomy · Build · Observe · Interop · Finance · Health · Knowledge · Family · Comms · Admin |

No further sign-off needed before scaffolding.

---

## @claude — review & implementation mandate

Please do a full pass with the goal of shipping production HUD v2. Specifically:

### 1. Review for bugs / correctness
- Read `docs/design/HUD_V2_HANDOFF.md` end-to-end first, then `v2-style.css`, then the modules.
- Open `hud-v2/hud-v2.html` in a browser and exercise every surface: cockpit submit→cognition flow, network focus mode, mode switching (rail + tabs toggle), ⌘K palette, EN/RO toggle, ambient mode, dossier slide-in, trust kill-switch, memory KG time-slider.
- Flag anything broken, inconsistent, or fragile. Note: the **screenshot/thumbnail tooling renders the main area black/white** because of `backdrop-filter` — the real browser is correct; do not "fix" that by stripping effects.

### 2. Missing backend features to implement (currently mocked in `v2-data.jsx`)
These are stubbed with constants/timers and must be wired to the real backend (`data.js` already fetches `/api/agents`, `/status`, `/dashboard`, `/tasks`, `/ticker`):

- [ ] **Cognition trace** — replace the `setTimeout` sequence in `v2-app.jsx` with a real **streaming** orchestrator (SSE): classify → route → gather → synthesize, with live agent scores, plugin reads, and redactions. Keep the 4-stage visual.
- [ ] **Conversation** — wire to the real chat/agent endpoint; token-by-token synthesis; real provenance (agents consulted, plugins, local/cloud, confidence).
- [ ] **Trust · audit chain** — render the real append-only **Merkle log**; verify hashes client-side; add a visible tamper-check action.
- [ ] **Trust · kill-switch** — hit the real halt-all endpoint with a confirm step + audit entry (currently a local toggle).
- [ ] **Trust · % local meter** — wire `localPct` (hard-coded 87) to real compute-locality telemetry.
- [ ] **Trust · capabilities & payments** — real capability grants; payments approval flow.
- [ ] **Memory · KG** — load the real **bitemporal** graph; the time-slider should query "as-of" snapshots, not filter a static `born` field. Wire fused recall + topic decay to real memory stats.
- [ ] **Roster / network / ticker / weather / calendar / heartbeat** — replace mock arrays with live `data.js` data (keys already match the product).
- [ ] **Settings** — the Tweaks axes (accent / density / motion / language / texture) become real persisted user preferences; remove `tweaks-panel.jsx`.

### 3. Implement production version
- Scaffold **Vite + React + TS**; self-host Space Grotesk + JetBrains Mono (follow existing `fonts.css` vendoring pattern).
- Port `v2-style.css` as-is (framework-agnostic — locks the look immediately).
- Port `v2-data.jsx` → typed models; swap mock for `loadJarvisData()`.
- Port primitives → shell → modes; **drop the `window` export/re-import pattern**, use ES modules.
- **D3:** fold Admin in as a mode using the existing token system (zero new colors).
- Fast-follow modes on the same primitives: Autonomy → Observe → Build → Interop.

### 4. Improve where production demands
See `HUD_V2_HANDOFF.md §7` (accessibility/keyboard nav, idle-pause for the 24/7 wall display, force-directed network layout, responsive breakpoints under ~1100px, deeper ambient mode).

---

## How to open this PR (for the human)

Read-only tooling can't push from here, so:

```bash
git checkout -b feat/hud-v2-prototype
# copy the bundle contents into the repo (keep the hud-v2/ and docs/design/ layout)
git add hud-v2 docs/design
git commit -m "feat(hud): HUD v2 design prototype + implementation handoff

- Interactive prototype: Cockpit/Agents/Trust/Memory + Ambient, ⌘K, EN/RO
- Full design system in v2-style.css (look/accent/density/motion tokens)
- docs/design/HUD_V2_HANDOFF.md — architecture, data contract, build plan
- D1–D4 locked (rail IA, Vite+React+TS, unify Admin, 4-mode v1 scope)"
git push -u origin feat/hud-v2-prototype
gh pr create --title "HUD v2 — design prototype + handoff (review & implement)" --body-file PULL_REQUEST.md
```

Then assign / @-mention Claude Code on the PR to start the review-and-implement pass.
