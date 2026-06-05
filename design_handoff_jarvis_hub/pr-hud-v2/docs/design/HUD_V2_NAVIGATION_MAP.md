# HUD v2 — Navigation Map

> A guide to **what you're navigating**: every mode, what it shows, who owns it, the file/component that renders it, its data on `window.V2`, and how a user reaches it. Pair this with `HUD_V2_HANDOFF.md` (architecture + build plan). This is a **design prototype** — review only; build the production version per the handoff.

---

## Navigation model

Three ways to move, all driven by the same `MODES` array in **`v2-shell.jsx`**:

1. **Rail** (default) — vertical mode list on the left (`Rail` component). Toggle via Tweaks → Navigation.
2. **Tabs** — horizontal bar (`Tabs` component), same `MODES`.
3. **Command palette** — `⌘K` / `Ctrl+K` (`Palette` component) — fuzzy jump to any mode + theme actions.

Active mode is a single `mode` string in **`v2-app.jsx`**; each mode renders in a `.workzone` (`full`, `wide`, or `cockpit` grid). `MODES` entries with `{sep:true}` draw a divider — they group the rail into **core · capability · life · system**.

### Keyboard
| Key | Mode | | Key | Mode |
|---|---|---|---|---|
| `1` | Cockpit | | `7` | Observe |
| `2` | Agents | | `8` | Interop |
| `3` | Trust | | `9` | Chat |
| `4` | Memory | | `0` | Comms |
| `5` | Autonomy | | `A` | Ambient view |
| `6` | Build | | `⌘K` | Palette (everything) |

Finance · Health · Knowledge · Family · Admin have no number — reach via rail/tabs or `⌘K`.

---

## The 15 modes

### Core (daily)
| Mode | Hotkey | What it shows | Component · file | Data |
|---|---|---|---|---|
| **Cockpit** | `1` | 3-col command center: roster · **network brain** + conversation/**cognition trace** · context (decisions, weather, schedule, heartbeat) | `App` cockpit branch · `v2-app.jsx`; `NetworkBrain` `v2-network.jsx`; `Conversation`/`CognitionStream` `v2-cockpit.jsx`; `RosterColumn`/`ContextColumn` `v2-shell.jsx` | `AGENTS, COLLAB, DECISIONS, WEATHER, CALENDAR, HEARTBEAT, TICKER` |
| **Chat** | `9` | Distraction-free direct line to Jarvis. Same `messages` state as Cockpit; **ticker hidden** | `ChatMode` · `v2-modes3.jsx` | shares `SEED_MESSAGES` / live convo |
| **Agents** | `2` | Roster grid by tier → slide-in **Dossier** (soul, runtime, plugins, collaborators) | `AgentsMode`,`Dossier` · `v2-modes.jsx` | `AGENTS, TIERS, DOSSIER, COLLAB` |

### Capability (the platform)
| Mode | Hotkey | What it shows | Component · file | Data |
|---|---|---|---|---|
| **Trust** | `3` | Merkle **audit chain** · **kill-switch** · **% local** meter · capabilities · payments | `TrustMode` · `v2-modes.jsx` | `AUDIT_CHAIN, CAPABILITIES, PAYMENTS` |
| **Memory** | `4` | Stats · fused recall · topic decay · **bitemporal KG** w/ time-slider | `MemoryMode` · `v2-modes.jsx` | `MEMORY_STATS, RECALLS, TOPICS, KG` |
| **Autonomy** | `5` | Ranked morning brief · observer log · **AUTO/ASK/OFF** policies w/ budgets | `AutonomyMode` · `v2-modes2.jsx` | `AUTONOMY` |
| **Build** | `6` | **Workflow DAG canvas** · skills marketplace · router sandbox | `BuildMode` · `v2-modes2.jsx` | `BUILD` |
| **Observe** | `7` | Quality stats · **traces w/ stage breakdowns** · model arena · per-agent latency · resilience | `ObserveMode` · `v2-modes2.jsx` | `OBSERVE` |
| **Interop** | `8` | A2A peers · MCP servers · widgets · webhooks | `InteropMode` · `v2-modes2.jsx` | `INTEROP` |

### Life (agent "homes")
| Mode | Owner | What it shows | Component · file | Data |
|---|---|---|---|---|
| **Finance** | Gecko | Net worth · accounts · budgets · FX/crypto watches · pending payments | `FinanceMode` · `v2-modes4.jsx` | `FINANCE` |
| **Health** | Hercules | Activity rings · sleep/HR/HRV/weight · weekly bars · plan · on-device sync | `HealthMode` · `v2-modes4.jsx` | `HEALTH` |
| **Knowledge** | Vision | Research queue · saved+cited · daily digest | `KnowledgeMode` · `v2-modes4.jsx` | `KNOWLEDGE` |
| **Family** | Frigga | **Local-only** space · members · events · reminders (on-device banner) | `FamilyMode` · `v2-modes4.jsx` | `FAMILY` |

### System
| Mode | Hotkey | What it shows | Component · file | Data |
|---|---|---|---|---|
| **Comms** | `0` | Unified inbox (Telegram/email/WhatsApp/voice) · filters · reading pane · which agent handled | `CommsMode` · `v2-modes3.jsx` | `COMMS` |
| **Admin** | — | Models & backends · plugin registry (toggles) · API keys · channels · backups · host (**D3 unification**) | `AdminMode` · `v2-modes3.jsx` | `ADMIN` |

---

## Cross-cutting (not modes)

| Surface | Trigger | Component · file |
|---|---|---|
| **Top bar** | always | `TopBar` · `v2-shell.jsx` (clock, online/% local, lang, ambient, ⌘K) |
| **Situation ticker** | always (hidden in Chat) | `Ticker` · `v2-shell.jsx` ← `TICKER` |
| **Command palette** | `⌘K` | `Palette` · `v2-shell.jsx` |
| **Ambient view** | `A` / top bar | `Ambient` · `v2-shell.jsx` (24/7 wall display: clock, EKG, pending) |
| **Provenance modal** | click a prov-chip | `ProvModal` · `v2-app.jsx` |
| **Tweaks panel** | host edit-mode | `tweaks-panel.jsx` (look/accent/density/IA/motion/texture/language/mode) — **prototype only** |

## File → modes quick index
- `v2-modes.jsx` → Agents, Dossier, Trust, Memory
- `v2-modes2.jsx` → Autonomy, Build, Observe, Interop
- `v2-modes3.jsx` → Chat, Comms, Admin
- `v2-modes4.jsx` → Finance, Health, Knowledge, Family
- `v2-cockpit.jsx` → Conversation, Cognition, Input (used by Cockpit + Chat)
- `v2-network.jsx` → NetworkBrain (Cockpit)
- `v2-shell.jsx` → all chrome + nav + palette + ambient
- `v2-app.jsx` → root state, the `mode` switch, hotkeys, submit→cognition flow

> Adding a mode = 5 touch points: a `MODES` entry (`v2-shell.jsx`), a palette item (`Palette`), a render branch (`v2-app.jsx`), the component (a `v2-modes*.jsx`), and its data on `window.V2` (`v2-data.jsx`). All four `v2-modes*.jsx` files follow the same `ModePanel` + `SubH` + `.admin-grid` two-column pattern — copy any one as a template.
