# Jarvis Hub — Single-Page HUD Design Brief (for Claude · Design)

> **Audience:** a Claude design session (or Figma Make / artifacts) tasked with conceiving a **new
> single-page interface** for Jarvis Hub. Everything lives on **ONE page** — no multi-page routing.
> Use zones, progressive disclosure, panels, a command palette, drawers, and overlays.
>
> **The one job:** a single page where **every developed human-facing capability is reachable**, the
> local-first **trust story is always visible**, and the **roadmap has room to grow** — while feeling
> **calmer than today**, not busier.
>
> **Status:** brief only. Generated 2026-06-27 from a full codebase + roadmap audit (~311 routes
> across 45 routers, 17 active agents, the shipped `frontend/src` HUD, `BACKLOG.md` Competitive-Gap
> Roadmap + ORIZONT 24). Supersedes the older multi-mode `docs/design/HUD_V2_BRIEF.md` for the
> *single-page* framing; reuse that doc's deep capability/endpoint appendix as reference.

---

## 0 · TL;DR

1. Jarvis Hub is no longer "a chat box with a network graph." It is **~30 capability areas / 311
   endpoints / 17 agents**, and the backend has repeatedly run ahead of the UI. The central design
   problem is **information architecture**: making that whole surface *legible and calm on one page*.
2. **Success criterion — the only one that matters: _no built feature is left unreachable._** The
   repo already enforces this mechanically: a **route-parity gate** (`tests/test_hud_v2_parity.py`)
   maps **every** backend route to either a UI surface **or** an explicit `NOT_IN_HUD` tag. Your IA
   is "done" when every human-facing route has a real home and only owner/internal routes are
   `NOT_IN_HUD`. Design *to that gate.*
3. Keep the shipped design language (dark HUD cockpit, Space Grotesk + JetBrains Mono, signal-cyan
   on void, corner-bracket panels, arc-reactor, situation ticker). **Evolve, don't abandon.**
4. Honour the non-negotiables: local-first trust always visible, calm-not-noisy, inspectable &
   forgettable, bilingual RO/EN, keyboard-first, honest LIVE/DEMO/OFFLINE states, offline-clean.
5. Reserve space for the roadmap (Action Kernel action-ledger, Verification-Fabric "proven" badges,
   kill-switch + credential quarantine, capture/missions/mesh/media) **and respect the explicit
   non-goals** (no managed-cloud billing UI, no multi-tenant team UI, no cloud-VLM uploads).

If you remember one sentence: **make the most capable local AI on earth feel like one calm,
trustworthy instrument on a single page — not a dashboard graveyard, and not a feature that exists in
code but nobody can reach.**

---

## 1 · Context & product

**Jarvis Hub** is a local-first, governed, proactive **personal AI operating system** — *"a private AI
that works while you sleep and is owned by the person it serves."* It runs **17 specialist agents (the
Cabinet)** across four tiers (CNS/Command · BIZ/Business · SEC/Tech · FND/Foundation) on the owner's
own GPU, **$0/month**. Its category-creating wedge is the intersection nobody else ships in one
system: **local-first + proactive autonomy + living memory + observability + governance.**

The UI is **"the HUD"** — a calm, premium dark cockpit you *command*, not a dashboard you *watch*. The
bar: *"a Bloomberg Terminal as Apple would have designed it in 2035, for one person who owns the whole
machine."*

**North-star metric:** weekly **accepted autonomous actions per user**, governed by four
counter-metrics — interrupt rate (≤4 urgent/day), reject rate, **%-local compute**, and p95 turn
latency. The soul of the product is *trust made visible*: every fact editable/forgettable, every
action audited, every cloud hop opt-in and visible. (`MOONSHOT.md`, `docs/METRICS.md`.)

---

## 2 · The brief's one job

Design a **single-page interface where every developed human-facing capability is reachable**, the
local-first trust story is **always visible**, and the roadmap has room to grow — while feeling
**calmer than today**, not busier.

> **Success criterion (the one that matters): _No built feature is left unreachable._**
>
> Today the backend exposes **~311 routes across 45 routers**; the always-visible rail calls only a
> handful directly, and the highest-value surfaces — the autonomy **Decision Inbox**, the **memory
> editor**, **missions**, **mesh** — are either demo-mocked or buried behind two keyboard-only
> overlays (the backtick **Console** and the `W` **World** overlay). This redesign closes that gap:
> every capability gets a deliberate home — surfaced, nested, or palette-only — but **decided**.
>
> **This is testable, not aspirational.** The repo's **parity gate**
> (`tests/test_hud_v2_parity.py`) already requires every route to map to a surface or an explicit
> `NOT_IN_HUD`. Treat that gate as the acceptance contract: when you finish, every *human-facing*
> route resolves to a home in §6, and only the §10 owner/internal routes remain `NOT_IN_HUD`.

Secondary goals: **dissolve the two hidden overlays** (Console, World) into discoverable homes;
promote Trust/Governance from buried panels to first-class; wire (or honestly mark) the demo-only
"agent-home" modes.

---

## 3 · Who & context of use

| | |
|---|---|
| **Primary user** | The **owner** — a single power-user who owns the whole machine. Keyboard-first, density-tolerant, wants depth on demand and silence otherwise. No onboarding hand-holding. |
| **Later** | Design-partners / a digital household. **Multi-user is a post-1.0 owner *decision*, not a given** (see §8 + non-goals) — reserve a light seam, don't build account UI. |
| **Primary surface** | **Desktop cockpit** — large screen, three-column workzone, dense. |
| **Secondary** | **Mobile / PWA** (installable, offline shell) — collapses to a single scrollable column + bottom action bar. |
| **Tertiary** | **Ambient / always-on wall display** — runs 24/7; beautiful at a glance and at arm's length; never flickers, nags, or churns. |

---

## 4 · Hard constraints & non-negotiables

1. **Single page.** No multi-page routing. Use zones, view-switching in the primary canvas, drawers,
   overlays, and a command palette.
2. **Local-first trust badges ALWAYS visible** in the top bar: **EGRESS** (`⊘ SEALED` strict-local
   vs `↗ HYBRID`), **%-LOCAL** compute meter, **MIC** (`● ON` / `⊘ MUTED`), plus **LLM**, **AGENTS**,
   and the **DATA** honesty badge. These never scroll away, never collapse below a fold, never get
   demoted into a drawer — on every surface, every breakpoint.
3. **Live / Demo / Offline / Empty state machine** is mandatory and explicit. Never present
   seeded/demo data as real — watermark DEMO; show "not connected" empty states; controls that can't
   work (kill-switch in demo) say **"unavailable"**, never fake success. Poll no faster than ~30s.
4. **Calm-not-noisy.** Interrupts are **budgeted (≤4 urgent/day)** → a few high-signal **decision
   cards**, not a feed. Motion only reflects *real* activity. ≤ a few always-on animations. Honor
   `prefers-reduced-motion` + a `data-motion="calm"` mode.
5. **Inspectable & forgettable.** Any surface that shows data must let the user **edit/forget** it.
   Per-fact inspect/edit/delete is a non-negotiable principle (`MOONSHOT.md` §5.3), not a settings page.
6. **Bilingual EN/RO.** Every string through i18n. Romanian is real product copy — never
   machine-translate or flatten it. (A CI test, `i18n-completeness`, fails on a missing/blank string.)
7. **Keyboard-first.** `⌘K` command palette + hotkeys are the connective tissue. Hotkeys `1`–`0`
   address the ten primary rail modes; the **Life** group and overlays use a `g`+letter chord so
   **every** mode and overlay is keyboard-reachable (no mode is mouse-only). Visible `:focus-visible`
   (2px accent outline). WCAG contrast on dark. Modals trap focus + lock scroll.
8. **Offline-clean & self-hosted.** No required external CDN/fonts/analytics at runtime (fonts as
   woff2). Degrade gracefully when the backend is partially down — never hard-fail (the "recall never
   hard-fails" ethos).
9. **Performance.** Instant for everything that isn't an LLM call; stream LLM via SSE with a legible
   thinking trace; never block first paint; lazy-load heavy surfaces (brain, workflow canvas, KG browser).
10. **Three auth tiers respected.** Open / user-guard / admin-guard. Handle 401/403 with in-app token
    entry (never `window.prompt`). Admin/payments/kill-switch-engage are admin-guarded.
11. **Stack reality.** The shipped frontend is **Vite + TypeScript + React** (`frontend/src/*.tsx`,
    `styles.css`) — *not* the no-build React-via-CDN of the old brief. Match the shipped stack; the
    backend API contract is fixed (add endpoints, don't break shapes; new polling routes → `_NO_STORE_PATHS`).

### Progressive-disclosure budget (makes "calmer" testable, not a hope)

The §6 IA is a superset of every built capability; calm is enforced by **counts, not vibes**:

- **Rail ≤ 10 first-class modes.** The four demo agent-homes (Finance/Health/Family/Knowledge)
  collapse into **one "Life" mode-group**, not four rail slots. Final rail: **Cockpit · Decisions ·
  Agents · Memory · Autonomy · Missions · Trust · Build · Observe · Interop+Mesh** — plus **Life**
  and **World** under the `g`-chord cluster, plus the owner **Admin Console** drawer.
- **≤ 5 first-class cards visible per view before paint.** Beyond that → a sub-tab, accordion,
  drawer, or palette-only. No view paints a wall of panels.
- **≤ 6 sub-tabs per view.** If a view needs more, group them (e.g. Memory folds eval/entities/
  reflection under *Hygiene*) — never a tab strip that wraps.
- **Right context column ≤ 4 cards**, and it **swaps content by mode** (never mirrors the active canvas).
- **Palette-only is a legitimate home.** The acceptance test is *reachable within two keystrokes or
  one click*, not *visible at all times*.

---

## 5 · Design language — *evolve, don't abandon*

The shipped HUD (`frontend/src/styles.css`) is the canonical design system. **Keep its grammar;
refine the IA on top of it.**

**Type**
- UI/display: **Space Grotesk** (600/500 headlines, 400 body).
- Data/labels/code/timestamps: **JetBrains Mono**, tabular numerals everywhere.
- **Letter-spaced UPPERCASE mono micro-labels are THE signature element** (panel titles `.16em`,
  wordmark `.26em`, micro-caps 8–10px).

**Palette (default Obsidian look + cyan accent)**
- Void: `--void #04070e`, `--void-2 #060b15` (near-black, blue undertone, dominant).
- Glass surfaces: `--surface rgba(10,22,38,.55)`, `--surface-2 rgba(13,27,46,.72)`.
- Hairlines: `--panel-line rgba(120,190,240,.12)`; brackets `rgba(140,205,250,.42)`.
- Ink ramp: `--ink #e9f4fd` → `.62` → `.34` → `.18`.
- Accent signal-cyan: `--accent #2bb8f0`, `--accent-light #8fe0ff`, glow `.45`.
- **Status semantics (consistent everywhere): green `#41f59b` = local/verified/success · violet
  `#a78bfa` = cloud/outbound · amber `#ffc24d` = caution/ASK/demo · red `#ff5a52` = halt/kill (sparingly).**

**Theming contract (keep intact):** `data-accent` (cyan/amber/green/violet) × `data-look`
(obsidian/graphite) × `data-density` (compact/normal/comfy) × `data-motion` (full/calm) ×
`data-scanline` / `data-dotgrid`. Persisted in localStorage; applied pre-paint.

**Signature motifs to reuse:** arc-reactor logo (counter-rotating rings) · corner-bracket "Obsidian"
panel frames (`.bk` 9px L-shapes) · notched/clip-path message bubbles · glowing tabular mono numerals
(big clock, hero numbers) · the neural-network **brain** (hex agent nodes + collab edges + packets on
*live* edges only) · the **situation ticker** (severity-tinted marquee, red "LIVE" head) · the
**cognition thinking-trace** rail (classify→route→synthesize) · `⌘K` palette · the **physical round
kill-switch** (red circle + pulse ring) · the **%-local-vs-cloud locality meter** · the **Merkle
audit chain** (rotated hash-dots + verified rows) · the **bitemporal KG time-slider** · **decision
cards** (`.dcard`, tags: anticip/signal/nudge/alert) · faint dot-grid + thin CRT scanlines.

**Do:** generous void margins · one idea per surface · real product data as texture · thin cyan
hairlines · mono micro-labels for structure · left-aligned calm hierarchy · *show the work* (routing,
provenance, audit chain, kill-switch).
**Don't:** gradients-for-the-sake-of-it · neon glow soup · stock photos · emoji headlines · >1
competing accent · fabricated/fake-stat mockups (demo/seed must be badged — that honesty IS the brand).

---

## 6 · Complete capability map → Information Architecture

### Proposed single-page zone layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ COMMAND BAR / REACTOR HEADER                                               │
│ ⊙ reactor + wordmark · ⏱ big mono clock · [AGENTS][LLM][DATA][%LOCAL]      │
│ [EGRESS ⊘SEALED][MIC] · ⌘K · EN/RO · theme tools · ◐ identity slot        │
├──────────────────────────────────────────────────────────────────────────┤
│ SITUATION TICKER (severity-tinted; hidden in Chat/Ambient)                 │
├────────┬──────────────────────────────────────────┬───────────────────────┤
│ AGENT  │  PRIMARY WORK CANVAS                      │  CONTEXT COLUMN        │
│ RAIL   │  (switchable VIEWS, never a new page)     │  (mode-swapping; ≤4)   │
│ Cabinet│  Cockpit · Decisions · Agents · Memory    │  default: Decision     │
│ tiers, │  · Autonomy · Missions · Trust · Build    │   queue · Weather/Sched│
│ status │  · Observe · Interop+Mesh                 │   · Heartbeat · Notes  │
│ dots;  │  + Life group (Fin/Health/Family/Know)    │  on Decisions: budget +│
│ ≤10 +  │  + World (g-chord)                        │   escalations instead  │
│ Life   │                                           │  (never mirrors canvas)│
├────────┴──────────────────────────────────────────┴───────────────────────┤
│ DRAWERS (slide-over): Dossier · KG editor · Mission workspace · Trust deep │
│ OVERLAYS: ⌘K palette · Ambient (A) · Admin Console (owner) · World (W)     │
└──────────────────────────────────────────────────────────────────────────┘
   ⌘K Command Palette overlays everything (agents, tasks, settings, jump-to-mode, actions)
```

**Navigation model:** left **mode rail** (icons; hotkeys `1`–`0` for the ten primary modes, `g`+letter
for Life/World/overlays) switches the **primary canvas view** — *nothing routes*. The **right context
column swaps content per mode** (on Decisions it shows interrupt-budget + escalations, never a second
copy of the queue). **Drawers** slide over for deep tools. The **command palette** reaches *every*
view + action. The **Admin Console** is a single owner-gated drawer (replacing the hidden backtick
overlay). **Ambient** and **World** stay overlays but also get rail/chord/palette entries (no longer
keyboard-only secrets). A quiet **identity slot** in the command bar reserves space for a future
profile switch (see §8 — light seam only).

### Capability → IA table

Priority key: **P0** = always-visible / first-class rail mode · **P1** = one action away (tab, drawer,
context card) · **P2** = in a drawer / palette-only / owner console.

| Capability | Where it lives on the page | Priority | Notes |
|---|---|---|---|
| **Chat (blocking + streaming SSE)** | Cockpit canvas, center conversation | P0 | Core entry; token stream + cognition trace + provenance chip. |
| **Voice STT/TTS, hands-free, PTT, barge-in** | Cockpit input bar + config popover | P0 | `/api/voice/capabilities` gates honestly; mic badge reflects mute. |
| **Cognition trace + provenance modal** | Inline under each turn | P0 | classify→route→gather→synthesize; agents/plugins/locality/confidence. |
| **Neural-Mesh brain** | Cockpit center-top (embedded) + Observe | P0 | Packets animate only on *live* edges. |
| **Agent roster (Cabinet, 4 tiers)** | Agent rail (persistent) + Agents view | P0 | Status dots; click → Dossier drawer. |
| **Agent dossier (live SOUL.md, run history, plugins, skills)** | Dossier **drawer** | P1 | Make skills browsable (count-only today). |
| **Decision Inbox — accept/edit/reject/defer** | **NEW P0 "Decisions" mode** + live badge-counted queue in context column | **P0** | THE north-star surface. Card: dry-run preview, reversible/irreversible bucket, wired to `/autonomy/tasks/{id}/decision`. *Demo-seed only today — the single highest-value gap.* |
| **Action-level tool-call approvals + dry-run** | Inside a Decision card → expandable "tool calls" sub-list, each with Preview | P1 | `/api/actions/*`, `/api/autonomy/preview`. Counts into badge. |
| **Browser-action plan preview (consent before execute)** | Decision card "Pre-flight" sub-panel + palette action | P1 | `/api/browser/check`, `/api/browser/plan/preview`. *No UI today.* |
| **Autonomy global mode AUTO/ASK/OFF** | Autonomy view header switch | P0 | The one live autonomy control today; keep prominent. |
| **Morning brief / evening retro digest** | Autonomy view + context card | P1 | `/autonomy/brief`; surface evening retro too. |
| **Proactive observer + run-now** | Autonomy view (observer log + manual run button) | P1 | Expose the run-now button (hidden today). |
| **Autonomy-raise preference suggestions** | Autonomy view banner | P1 | `/autonomy/preferences/suggestions`. |
| **Escalation routing + governed outbound-call broker** | "Escalations & calls" panel — context column on Decisions | P1 | `/api/autonomy/call` — budget + approval gated; no UI today. |
| **Interrupt budget (≤N/day)** | Context column on Decisions + Observe meter | P1 | Render `/autonomy/status` budget block, not just the meter. |
| **Context compress + digest run** | Autonomy "Tools" strip + palette actions | P2 | `/api/context/compress`, `/api/digest/run`. |
| **NL scheduling (phrase→cron)** | Palette action + Autonomy "Tools" strip | P2 | `/api/schedule/parse`. |
| **Missions (long-running work units)** | **NEW P1 "Missions" mode** — board → workspace **drawer** (plan, budget meter, artifacts, audit, pause/resume) | **P1** | 9 endpoints, zero UI today. |
| **Memory stats + recalls** | Memory → *Recall* sub-tab | P0 | `/memory/stats`, `/api/memory/search`. |
| **Remember-a-fact write form** | Memory → *Recall* inline "Remember" composer | P1 | `/api/memory/remember`. No UI today; completes inspect/edit/forget. |
| **KG editor — entities/relations CRUD, inline edit/delete** | Memory → *Graph* sub-tab + KG editor **drawer** | P1 | *Read-only today.* Non-negotiable: see/edit/delete any fact. |
| **Named-entity store + agentic-RAG `search_memory` tool-spec** | Memory → *Graph* entity list (read) | P2 | `/api/memory/entities`, `/tool-spec`, `/search-tool`. |
| **Per-fact FORGET** | Per-fact "Forget" button in Memory + KG drawer | P1 | `/api/memory/decay/forget`; the §4.5 principle made interactive. |
| **Bitemporal facts — as-of / history time-travel** | Memory → *Time-travel* sub-tab (real slider) | P1 | `/facts/as-of`, `/facts/history`. *Mocked today.* |
| **KG ingest from text** | Memory → *Ingest* sub-tab | P1 | `/api/kg/ingest`. |
| **Consolidation review, decay candidates, nightly reflection, memory-eval** | Memory → *Hygiene* sub-tab (grouped) | P2 | `/api/memory/consolidate`, `/decay/candidates`, `/api/reflection/status`+`/run`, `/api/memory/eval/*`. |
| **Capture (ambient ingest) — list/ingest/delete** | Memory → *Capture* sub-tab | P2 | `/api/capture` + per-item delete (privacy promise). |
| **Data spaces / memory profile + local-docs indexer** | Memory → *Spaces* sub-tab ("Index folder") | P2 | `/api/local-docs/index`, spaces. |
| **Trust Center — kill-switch** | Trust view (big round red STOP) | P0 | `/api/security/kill-switch`. Deliberate admin exception, surfaced. |
| **Security spotlight + prompt-injection scan** | Trust view **"Pre-flight / Scan" card** | P1 | `/api/security/spotlight`, `/scan-injection`. Datamark untrusted content. |
| **Merkle audit chain verify + chain rows** | Trust view audit panel | P0 | Wire the *real* chain rows (`/audit/intent`), not the seeded list. |
| **Intent-attribution audit + transparency anchors** | "Who/Why" provenance **drawer** on audit panel | P1 | `/audit/intent`, `/audit/anchors`. |
| **Capability grants / tokens (live broker) + "proven" registry read** | Trust view capability table (with ✓-proven chip slot) | P1 | *Hardcoded demo today* — wire to live broker; surface readiness (§8 V2). |
| **Governance scorecard + security posture + loop-breaker** | Trust view cards (Governance / Readiness / Loop-breaker) | P1 | `/governance`, `/posture`, `/loop-breaker(+/reset)`. No UI today. |
| **%-local locality ring + per-reply provenance** | Trust ring + top-bar badge + per-message chip | P0 | Persistent trust signal (`/api/analytics/locality`). |
| **Network / egress monitor (LOCAL_ONLY proof)** | Trust "Egress proof" card | P1 | `/api/admin/network/calls` — strongest privacy proof; belongs in Trust. |
| **Per-cloud-hop opt-in toggle** | Trust (reserved affordance) | P1 | Roadmap: make EGRESS user-toggleable, not read-only. |
| **Backup / export / forget-me** | "Export my data" / "Forget me" in Trust (confirm-gated) + Admin | P1 | `/api/admin/export`, `/forget`. GDPR promise; fake list today. |
| **Workflows / pipelines — run, traces, AI step builder** | Build view (make LIVE) | P1 | `/api/workflows` run + `/traces` overlay + `/step/generate` inline. *Static demo SVG today.* |
| **Skills marketplace — install/publish/review** | Build view marketplace tab | P1 | Install live; surface review/moderation. |
| **Sandbox code execution** | Build view → sandbox drawer | P2 | DEV_MODE-gated; honest 403 when off. |
| **Canvas (shared scratch surface)** | Build view panel or cockpit side-drawer | P2 | `/api/canvas` post/pin/clear. No UI today. |
| **Agent templates (instantiate)** | Build view → "New agent" | P2 | Graduate from console. |
| **Observe — north-star + counter-metrics** | Observe view meter | P0 | `/api/metrics/north-star`; honest em-dashes for null. |
| **Traces / quality / resilience / latency** | Observe view tiles | P1 | Composed live today; keep. |
| **Quality threshold control + per-response scores** | Observe "Quality" tile → threshold setter | P1 | `/api/quality/threshold` (set), `/scores` (read). |
| **Arena — run + vote + leaderboard** | Observe "Arena" tab | P1 | Expose run/vote (leaderboard-only today). |
| **Eval datasets + regression compare** | Observe "Evals" tab | P1 | Graduate from console. |
| **Human review queue (flag→vote→dataset)** | Observe "Review" tab | P1 | Graduate from console. |
| **Kernel decision meter (grant/deny/queue per kind)** | Observe "Kernel" tile (when Action Kernel on) | P1 | `/api/metrics/kernel`. Roadmap-live; see §8. |
| **Capability readiness board (SEAM→WIRED→VERIFIED→GA)** | Observe "Readiness" tile | P1 | `/api/metrics/capabilities`. Roadmap-live; see §8. |
| **Feedback (thumbs per reply)** | Thumbs on each assistant message | P1 | `/api/feedback`. No UI today; cheapest signal. |
| **Cost / usage meter (cloud-hop tied)** | Observe + Trust running meter | P1 | `/api/cost`. Buried in console today. |
| **Interop — A2A peers, MCP servers, widgets, webhooks** | Interop view (read) | P1 | Read-only lists today. |
| **A2A inbox approve/reject** | Interop view "Inbox" tab | P1 | Graduate from console; verified peers never auto-execute. |
| **Mesh — sync, satellites, nodes, tool-RPC, sub-agents** | **NEW "Mesh / Devices" panel in Interop** | P1 | 14 endpoints, zero UI. Pair a phone as mic satellite; register a node. |
| **Multimodal / VLM, media-gen, desktop preview** | Cockpit input bar (image attach → describe; generate media) + Observe desktop tile | P1 | `/api/vlm/describe`, `/media/generate`. No UI today. |
| **Rooms (multi-agent @-mention chat)** | Comms view — promote to live, non-demo-gated | P1 | `/api/rooms`. Hidden in console / demo today. |
| **Comms unified inbox (email/telegram/whatsapp)** | Comms view | P2 | Reply backend not wired — keep honest "preview" until live. |
| **Channel sender pairing** | Comms view "Pairing" tab (request) + Admin (decide) | P2 | Request public; decisions owner-only. |
| **Notes (injected into every turn) + AI rewrite** | Persistent **Notes card** in context column | P1 | Users must always see standing context steering answers. |
| **Sessions — list + resume** | Palette + Cockpit history menu | P1 | `/sessions`. |
| **WorldView / Argus — Signal Layer intelligence** | **"World" mode (g-chord)** + Observe inline panel | P1 | Brief, ranked signals, evidence drawer, Ask Argus. Off the rail today. |
| **Finance (Gecko)** | **Life** group → Finance view — wire to balance plugin or mark honest | P2 | Demo-mock today; connect `balance` or badge as preview. |
| **Health (Hercules)** | **Life** group → Health view — wire to apple-health or mark honest | P2 | Demo-mock; local-only. |
| **Family (Frigga, local-only)** | **Life** group → Family view — local-only banner, no cloud ever | P2 | Proof agent; lead trust stories with her. |
| **Knowledge (Vision/OSINT)** | **Life** group → Knowledge view — wire to websearch or mark honest | P2 | Demo-mock today. |
| **Heartbeat scheduler** | Admin console + context heartbeat feed | P2 | Graduate from console. |
| **Transcript → governed tasks** | Decisions view "Ingest transcript" action | P2 | Produces approval-queue items. |
| **Onboarding wizard + funnel** | First-run overlay (drive from backend) | P2 | `/api/onboarding/wizard`; one banner only. |
| **Admin / settings / models / prompts / secrets** | **Admin Console drawer (owner-gated)** | P2 | See §10. |

> **Memory sub-tab cap respected:** Recall · Graph · Time-travel · Ingest · Hygiene · Capture ·
> Spaces = 7 groups; eval/entities/reflection fold **under** existing tabs (Hygiene / Graph) rather
> than adding tab-strip sprawl.

---

## 7 · Built-but-currently-unreachable — MUST be wired in

These exist in code with **no real UI today** (verified: zero/​test-only frontend references). The
redesign's core mandate is to give each a reachable home (all are in §6; flagged here so nothing is
missed). This section directly answers the owner's fear — *"a feature is developed but cannot be used
by people in the interface."*

1. **Decision Inbox / task approval (accept·edit·reject·defer)** — *the north-star surface.* Works
   over Telegram but the web cockpit's decisions column is **demo-seed only**. → New **P0 Decisions
   mode** + live context-column queue. **Highest-value gap.**
2. **Action-level tool-call approvals + dry-run**, and **browser-action plan preview** → "Pre-flight"
   sub-panels inside each Decision card.
3. **Mission workspaces** (9 endpoints, zero consumer) → new **Missions mode** with workspace drawer.
4. **KG editor + bitemporal facts + ingest + decay-forget + remember-a-fact** — the "see/edit/delete
   any fact" principle is **read-only** today → interactive Memory view + KG drawer.
5. **Memory hygiene cluster** — nightly **reflection** (turns→entities/lessons→KG), **memory-eval**
   corpus/harness, consolidation, decay candidates → Memory *Hygiene* sub-tab.
6. **Security spotlight + injection scan** (Console-only today) → Trust **"Pre-flight / Scan" card**.
7. **Distributed mesh** (14 endpoints: sync, satellites, nodes, tool-RPC, sub-agents) → **Mesh/Devices
   panel** in Interop.
8. **Multimodal / VLM + media-gen + desktop preview** (no frontend ref at all) → cockpit input bar +
   Observe tile.
9. **Capture · Canvas · Feedback · Rooms · Review queue · Eval datasets · Escalation/outbound-call ·
   Notes · Backup/export/forget · Onboarding wizard · Governance/posture/loop-breaker · Egress
   monitor · Capability broker + "proven" registry · quality-threshold · context-compress/digest** —
   currently zero-UI or buried in the keyboard-only Console → graduated to discoverable tabs/cards per §6.
10. **WorldView/Argus** — only via the hidden `W` overlay → promote to a rail mode + Observe inline.

### Console dissolution — promotion table (resolves "graduate vs keep-hidden" explicitly)

Every Console panel is **decided**: it either graduates to a user-facing home, or it stays in the
owner Admin Console drawer. None left ambiguous.

| → **Graduates to a user-facing home** | → **Stays owner-gated in Admin Console drawer (§10)** |
|---|---|
| Sandbox · Eval datasets · Review queue · Rooms · Notes · Local-docs index · Reflection · Transcript→tasks · Escalation/calls · Capture · Canvas · Feedback · Egress monitor · Cost meter · Injection-scan/spotlight · Memory-eval · Context-compress/digest · Capability table (read) · A2A inbox · Mesh/devices · WorldView · Kernel/readiness meters | Settings/ops · Prompt versioning · Models / LM-Studio control · Secrets broker · Auth-profiles · Network/calls *admin* writes · Agent-templates *write* · Webhooks CRUD · Outbound-MCP mgmt · A2A peer mgmt · Channel-pairing *decisions* · Node register/delete · OAuth refresh / **Oracle sync-conflict resolution** · **Wyoming / server-side wake-word voice pipeline** · Learning/bench-agent promotion · Plugin enable/disable · Widget-token mint · Infra probes · Howard digital-twin |

> **Dissolve the hidden CONSOLE.** Its ~33 panels are de-facto promote-list items. The table above
> splits them cleanly so each either graduates to a discoverable home or is honestly owner-scoped —
> instead of staying behind the backtick key.

---

## 8 · Roadmap hooks — reserve space now (so the single page absorbs the future without a rewrite)

The authoritative roadmap is `BACKLOG.md` (Forward roadmap 0.12→1.0 · the ~48-theme **Competitive-Gap
Roadmap** · **ORIZONT 24 — "AI-OS"**). The IA above must reserve affordances for these. **Most are
already seeded in the backend** (~85%), so reserving space is cheap and correct.

### 8.1 ORIZONT 24 — the substrate (Action Kernel + Verification Fabric)

| Coming capability | UI affordance to reserve | Nearest shipped neighbour |
|---|---|---|
| **Action Kernel** — every agent action mediated, budgeted, revocable (one syscall table) | An **Action ledger / kernel-decision tile** in Observe (grant/deny/queue per kind, recent denials + reason) | `GET /api/metrics/kernel` already live behind `JARVIS_ACTION_KERNEL` |
| **The scheduler** — central token/time/money/**interrupt** budgets + loop detection (the ≤4/day guardrail in one place) | **Budgets** block in Decisions context column + a **loop-breaker** status/reset tile in Trust | `GET/POST /api/security/loop-breaker` live |
| **Kill-switch + credential quarantine as a syscall** (one-tap HUD) | The big **STOP** in Trust + a **credential-quarantine** affordance beside it ("revoke/quarantine compromised creds on halt") | kill-switch live; quarantine is the syscall's frontend tail |
| **Capabilities as process permissions** (least-privilege per agent) | The **capability grants table** in Trust (already in §6) deepens into per-agent scopes | `CapabilityBroker` issuance live |
| **Verification Fabric** — capability **readiness** SEAM→WIRED→VERIFIED→GA, reality-harness "proven" | A **Readiness board** tile in Observe + a **✓-proven chip** on capabilities in the Trust capability table | `GET /api/metrics/capabilities` live |
| **Eval → required release gate** with north-star + counter-metric guardrails | Guardrail-breach flags on the Observe north-star meter | `north_star.GUARDRAILS` live |

### 8.2 Competitive-Gap themes with a UI footprint (reserve a home or a tab)

- **Today In Jarvis (0.38)** — a unified chronological **timeline** of everything Jarvis did/learned.
  Reserve a "Today" view (palette + Cockpit context) over `autonomy/digest` + `memory/digest`.
- **Capture Inbox (0.26)** — phone export / transcript sync / inbox view → the Memory *Capture* sub-tab
  (already homed) grows an inbox.
- **Voice Persona Studio (0.28)** — consent + barge-in→HUD + persona selection → a voice-config drawer
  off the cockpit input bar.
- **Desktop Control Pack (0.25) + Screen-Capture Reflex (0.65) + Floating Bar / Global Hotkey (0.64)**
  — a **system-wide summon bar** (Tauri shell, `Cmd/Ctrl+/`) and one-keypress screenshot→VLM→answer.
  *Single-page implication:* design the cockpit composer so it can also render as a **thin floating
  overlay** (a compact command-bar variant), and reserve a "desktop preview" tile in Observe.
- **Media Library (0.46) + Publishing Studio (0.50) + Creative pipeline (0.47)** → Build view gains a
  **Media** tab (catalog / searchable timeline / export bundles) once `media_gen` is surfaced.
- **Market Intel (0.39) / OSINT Investigator (0.40) / World Signal Packs (0.41)** → deepen the World
  mode + the Life→Finance view (watchlists, alerts, evidence drawer, disclaimers).
- **Pack Manager (0.58) + Offline Knowledge Packs (0.21) + System Profiles (0.62)** → an Admin-drawer
  **Packs** panel (install/remove/rollback model/domain/content packs) and a profile switch
  (Gaming/AI/Multimedia/Admin) in the command bar's theme/tools cluster.
- **Jarvis Vault (0.20)** — a large local store + retention controls → fold into Memory *Spaces* /
  Admin retention, not a new rail mode.
- **SaaS Connector Breadth (0.66)** — Linear/Asana/Notion/Figma/M365/Google-Sheets/Apple etc. → the
  Interop integrations list must scale to **dozens** of connectors (search + categories), not a fixed grid.
- **First-Run Command Center (0.19) + activation funnel + Design-Partner feedback/NPS (H23.21/0.55)**
  → drive the first-run overlay from `/api/onboarding/wizard`; add a small **feedback/NPS** footer
  widget (`/api/feedback`).

### 8.3 The single-user → multi-user seam, and the explicit NON-GOALS

- **Multi-user / household** is a **post-1.0 owner decision** (`BACKLOG.md` H23.23; MOONSHOT Phase 3 /
  Orizont-8 stretch), *not* a committed feature. Reserve **only** the quiet **identity slot** in the
  command bar — do **not** design account-management, org, or team UI.
- **Explicit non-goals (designing these would betray the brand — `BACKLOG.md` 0.66 addendum):**
  - ❌ **Managed-cloud freemium + billing UI** — no "upgrade your plan", pricing, or paywall surfaces.
  - ❌ **Multi-tenant / team-workspace UI** — this is single-owner software; density is a feature.
  - ❌ **Uploading screenshots / data to a cloud VLM** — VLM "eyes" stay local; "we win these on
    privacy by *not* doing them."
  - The trust header's **EGRESS / %-LOCAL** badges exist precisely to make any drift from this visible.

---

## 9 · Key interactions & states

**Command palette (⌘K)** — fuzzy launcher: Go-to (every view + Life sub-views + World + Ambient +
Admin), Actions (new session, ingest transcript, parse schedule, compress context, run digest,
browser-plan preview, scan untrusted text, run eval, forget-me…), Theme (accent, EN/RO), Display
(density, scanline, dot-grid). Mono group headers, kbd hints, arrow/enter/esc.

**Decision card (the core loop)** — the product's most important component. A `.dcard` shows: kind tag
(**ACT / NOTIFY / ASK** → anticip/signal/nudge/alert), agent + why, **dry-run preview**, reversible
(green) vs irreversible (amber/red) bucket, and four actions: **Accept · Edit · Reject · Defer** wired
to `/autonomy/tasks/{id}/decision`. Expandable **Pre-flight** sub-list: per tool-call Preview, and for
browser/web actions a `/browser/plan/preview` consent step. Approving feels deliberate and reassuring
— confirm on irreversible, instant on reversible. Respects the interrupt budget (only urgent items push).

**Decisions-mode context column** — when Decisions is the active canvas, the right column does **not**
mirror the queue; it switches to **interrupt-budget + escalations/outbound-calls**, so canvas and
column complement rather than duplicate.

**Hands-free voice + barge-in** — mic in input bar; capabilities-gated; states: idle → listening →
transcribing → speaking; barge-in interrupts TTS. Honest degradation when STT/TTS unavailable. Mic
badge mirrors mute. Server-side wake-word (Wyoming/"Howard") is owner-scoped and marked scaffolded —
not the end-user mic path.

**Ambient mode (A)** — full-screen screensaver: giant mono clock, EKG line, active/total agents,
%-local, pending-decision count + top-3 cards. Calm motion only. Esc/click exits.

**Demo ↔ Live toggle** — watermarked DEMO banner with exit; `DATA` badge cycles
DEMO/LIVE/OFFLINE/EMPTY. Seeded data is always badged; nothing fake passes as real.
**Finance/Health/Family/Knowledge fallback IA:** if not wired by ship, they do **not** consume rail
slots — they stay inside the **Life** group, palette-reachable and watermarked DEMO.

**Empty / offline / loading** — per-tile "not connected" empty states; offline shell renders; chat
shows honest "model unreachable"; skeletons never block first paint; graceful 401/403 → in-app token
entry. A first-run banner appears only when `serverUp && !model && !demo` (one nudge, not a wizard).

**Mobile / PWA collapse (persistent column resolved)** — single scrollable column + bottom action bar.
The context column's pieces relocate explicitly: **decision queue → bottom-action-bar badge that opens
a sheet**; **Notes → a cockpit drawer**; **heartbeat feed → a collapsible section** below the
conversation; trust badges stay pinned in a compact top strip (never collapsed — §4.2). Life sub-views
are palette/sheet-reachable, not bottom-bar slots.

---

## 10 · What to deliberately NOT expose (owner / admin / internal)

Keep these behind a **single owner-gated Admin Console drawer** (replacing today's hidden backtick
overlay) — present but not on the end-user rail, nothing dangerous one click away. (See the §7
promotion table for the clean user-facing-vs-owner split.) These are the legitimate `NOT_IN_HUD`
entries for the parity gate.

- Admin settings/ops: `/api/admin/settings`, rotate-tokens, env, audit, apm, network/calls,
  agents/stats, llm/test.
- **Prompt versioning** (history/diff/commit/rollback/AB/preview) — owner prompt engineering.
- **Models / local LLM control** (load/unload/switch/server-start, auth-profiles, LM Studio).
- **Secrets broker** (store/list/delete, redact) — secret material never in the end-user surface.
- **Authority WRITES:** capability token *issue*, kill-switch *engage*, loop-breaker *reset*, audit
  *anchor*. *(Kill-switch STOP is the one deliberate exception, surfaced in Trust.)*
- **Backup/export/forget raw admin endpoints** (surface "Export"/"Forget me" to the user; keep raw
  endpoints owner-scoped, confirm-gated).
- **Payments mandate-setting** (per-payment approve/reject/settle is user-visible in Trust; mandate
  policy is owner).
- **Webhooks CRUD, outbound MCP server management, A2A peer management, channel pairing decisions,
  node register/delete.**
- **OAuth refresh / Oracle sync + sync-conflict resolution** — owner-scoped conflict-resolution drawer
  (`/api/oracle/conflicts`, `/resolve`).
- **Wyoming / server-side wake-word voice pipeline** — owner-scoped, marked "scaffolded — not wired."
- **Learning promotion + bench-agent promotion** (bench agents deliberately stay off the main roster).
- **Plugin enable/disable toggle, widget token minting.**
- **Infra probes** (`/healthz`, `/readyz`, `/metrics`), analytics beacon — invisible by design.
- **Howard digital-twin ingestion** — owner-only personal-corpus subsystem; even with a UI, an
  owner-scoped inspect/trigger panel, never end-user.

---

## 11 · Deliverables & acceptance checklist

**Deliver (single page, no routing):**
1. **Full single-page layout** — command/reactor header (with identity slot), situation ticker, agent
   rail (≤10 modes + Life group), switchable primary canvas, mode-swapping right context column,
   drawers, overlays.
2. **All primary canvas views** designed: Cockpit, **Decisions (new)**, Agents, Memory (interactive,
   ≤7 sub-tabs), Autonomy, **Missions (new)**, Trust Center, Build, Observe, Interop+**Mesh (new)**,
   **Life group (Finance/Health/Family/Knowledge)**, World, Comms, + Admin Console drawer.
3. **Key components:** decision card (ACT/NOTIFY/ASK + accept/edit/reject/defer + dry-run +
   browser-plan/tool-call Pre-flight), corner-bracket panels, kill-switch, Pre-flight/Scan card,
   %-local meter, Merkle audit chain, interactive KG editor + time-slider + remember-a-fact form,
   mission workspace drawer, agent dossier drawer, cognition trace, provenance chip, ⌘K palette,
   situation ticker, neural brain.
4. **Persistent trust header** — EGRESS/%-LOCAL/MIC/LLM/AGENTS/DATA badges with honest states, pinned
   at every breakpoint.
5. **Responsive + ambient variants** — desktop three-column, mobile/PWA single-column (with the §9
   column-collapse map), ambient wall display. *(Bonus: the cockpit composer's thin floating-bar
   variant for the roadmap 0.64 global-hotkey overlay.)*
6. **EN/RO** strings shown for at least the trust header, decision card, and one full view.
7. **All four data states** illustrated: LIVE, DEMO (watermarked), OFFLINE, EMPTY.
8. **Theming proof** — at least Obsidian+cyan default, plus one alt accent and the Graphite look.

**Acceptance checklist:**
- [ ] **Every capability in the §6 IA table has a reachable home** (surfaced, nested, or palette-only).
      *(First and most important — this is the §2 success criterion.)*
- [ ] **Parity-gate clean:** every human-facing backend route maps to a §6 surface; only the §10
      owner/internal routes are `NOT_IN_HUD`. (Mirrors `tests/test_hud_v2_parity.py`.)
- [ ] Every `built-but-unreachable` item from §7 — Decision Inbox, browser-plan preview,
      spotlight/injection-scan, reflection, memory-eval, remember-a-fact, entity store,
      quality-threshold, context-compress/digest, mesh, multimodal, Oracle conflict-resolution,
      Wyoming voice — is wired into a view/drawer/card or honestly owner-marked.
- [ ] The **§7 promotion table** is honored: each Console panel either graduates or stays owner-gated.
- [ ] **Progressive-disclosure budget met:** rail ≤10 modes (Life groups the 4 demo homes), ≤5
      first-class cards per view before paint, ≤6 sub-tabs per view, context column ≤4 cards and
      mode-swapping (never mirrors canvas).
- [ ] **Keyboard contract complete:** `1`–`0` for primary modes, `g`+letter for Life/World/overlays —
      **every** mode reachable; full keyboard nav + visible focus.
- [ ] The **Decision Inbox** is a first-class P0 surface with a live, badge-counted queue and the
      accept/edit/reject/defer loop + Pre-flight previews.
- [ ] Memory is **interactive** — per-fact inspect/edit/**forget** + **remember** + real as-of/history
      time-slider; reflection & memory-eval homed under Hygiene.
- [ ] Trust badges (EGRESS / %-LOCAL / MIC) are **always visible at every breakpoint**; cloud hops
      coded violet; local-only agents (frigga/ultron/howard) never imply cloud.
- [ ] LIVE/DEMO/OFFLINE/EMPTY states are explicit and honest; no seeded data passes as real;
      non-functional controls say "unavailable"; Finance/Health/Family/Knowledge demote to palette+DEMO
      inside Life if unwired.
- [ ] **Roadmap space reserved** per §8 (action ledger, readiness board, loop-breaker, credential
      quarantine, identity slot) **and non-goals respected** (no billing/team/cloud-VLM UI).
- [ ] Mobile collapse resolved: decision queue → bottom-bar sheet, Notes → cockpit drawer, heartbeat →
      collapsible section, trust strip pinned.
- [ ] Interrupt budget respected — decisions are a few high-signal cards, not a feed.
- [ ] `⌘K` reaches every view + key action; owner/admin/internal items (§10) live in the Admin Console
      drawer, not the end-user rail.
- [ ] The result feels **calmer than today** — measured by the §4 budget (mode/card/sub-tab caps), not
      by feel; no panel sprawl, no two-disconnected-apps seam, no required external CDN/fonts.
- [ ] Bilingual EN/RO; Romanian copy verbatim, not flattened.
- [ ] Honors `data-accent / data-look / data-density / data-motion / scanline / dotgrid` and
      green=local / violet=cloud / amber=caution / red=halt semantics.

---

## 12 · Appendix — where to read the ground truth

- **Vision / principles / north-star:** `MOONSHOT.md`, `docs/METRICS.md`.
- **Where code lives / lifecycle / recipes:** `docs/ARCHITECTURE.md` (module index, the 45 routers).
- **The whole HTTP surface:** `agents/core/routers/*.py` (+ 9 inline in `agents/web.py`).
- **Today's HUD (the thing being re-homed):** `frontend/src/*.tsx` (`shell.tsx` nav/topbar,
  `cockpit.tsx`, `modes*.tsx`, `gap.tsx` = the Console, `world-intelligence.tsx`), `styles.css`
  (canonical tokens), `frontend/src/api/*` (what's actually wired).
- **The coverage contract:** `tests/test_hud_v2_parity.py` (route → surface / `NOT_IN_HUD`) and the
  depth punch-list `docs/design/HUD_V2_REMAINING.md` (TASK-2).
- **Brand:** `docs/BRAND_BOOK.md` (voice, palette, "the Cabinet", "the HUD", Frigga = trust proof).
- **Roadmap (the future this page must absorb):** `BACKLOG.md` — Forward roadmap (0.12→1.0),
  Competitive-Gap Roadmap (~48 themes), **ORIZONT 24** (Action Kernel + Verification Fabric), plus the
  explicit non-goals in the 0.66 addendum.
- **Prior multi-mode brief (deeper endpoint appendix):** `docs/design/HUD_V2_BRIEF.md`.

---

*Assembled from a full codebase + roadmap audit on 2026-06-27 (~311 routes across 45 routers, the
shipped `frontend/src` HUD, and `BACKLOG.md`'s Competitive-Gap Roadmap + ORIZONT 24). Every built
capability is **decided** — surfaced, nested, palette-only, or honestly owner-scoped — so that no
feature exists in code that a person cannot reach in the interface.*
