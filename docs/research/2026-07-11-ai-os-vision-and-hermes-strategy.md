# AI-OS Vision & Hermes Strategy — owner session archive (2026-07-11)

> Date: 2026-07-11 · Status: **owner-decided** · Source: strategy conversation (full repo audit +
> "what should Jarvis become" vision session), owner = Andrei.
> This is an **immutable dated snapshot** (per `docs/AI_CONTEXT.md` rules) — the provenance for the
> 2026-07-11 strategy change. The living versions of everything here are `AI_OS_VISION.md`,
> `MOONSHOT.md` and `BACKLOG.md` (ORIZONT 27–33, H23.24–H23.28). Do not "fix" this file later.

---

## 1. Context

The owner ran a full repository audit with an external assistant session, then pushed the
conversation past the audit's launch-oriented framing into the actual long-term ambition:
not a better chatbot, but a **personal operating system for the house, devices, information and
digital life** — one that plays media, shows webpages, communicates, jokes well, monitors the
surveillance cameras, acts as a house brain, and **figures out how to do things it doesn't yet
know how to do** (runs scripts, uses the computer like a human).

The session produced three artifacts, all archived here: (a) the audit's findings and P0/P1
recommendations, (b) the six-pillar AI-OS capability vision, and (c) a Jarvis-vs-Hermes-Agent
comparison with an adopt-or-exceed strategy. The owner's closing decision: *"I want to be superior
to Hermes or integrate Hermes in Jarvis; I want the 3.0 version + Hermes as goal for this and all
of the above"* — i.e. the full vision is pulled **into** the 1.0 destination rather than deferred.

## 2. The audit findings kept (the proof track survives unchanged)

The audit's core verdict stands and is *not* weakened by the vision expansion: the system has been
proven to its tests, not yet to real users. Its P0/P1 items are preserved as the **proof half** of
the expanded 1.0 gate:

| Audit item | Where it landed |
|---|---|
| ⭐B0 governed-autonomy manual run + MANUAL_TESTING pass | unchanged — `docs/OWNER_TASKS.md`, BACKLOG Lane A A1 |
| 72h unattended soak, evidence recorded | unchanged — Lane A A2; **evidence collector** now spec'd as **H23.24** (`scripts/soak_report.py`) |
| Design partners: stranger-installs funnel (clone → install → model connected → first chat → first proactive action → first approved action → returns at day 7) | unchanged — Lane A A7, 0.20 product-proof |
| Doc drift (README ~3,848 vs BACKLOG ~3,868 vs STATUS ~4,068 vs GO_LIVE_PLAN v0.10-era) → generate volatile figures from one machine-readable file | **H23.26** — `project-status.json` + generated snippets, extending the existing `scripts/status_sync.py` (STATUS.md is already script-synced; the fix generalizes it) |
| One-command release gate (code-complete vs machine-verified vs owner-verified vs market-verified) | **H23.25** — `scripts/release_gate.py` |
| Design-partner telemetry packet (local, explicitly shared, no conversation content) | **H23.27** — `scripts/export_partner_feedback.py` |
| Positioning: lead with *"a private AI OS that works proactively but cannot silently act beyond the authority you gave it"*, not "17 agents"; soften unsupported competitive claims | README rewrite (same PR as this archive) |
| Freeze horizontal expansion with an automated gate | **H23.28** — the O26 park-list guard, actually implemented in CI (verified absent on 2026-07-11), with the freeze policy revised for the phased unpark (see §6) |

## 3. The vision as spoken

### 3.1 North star

> **Jarvis is a local-first Personal AI Operating System that can perceive, reason, communicate,
> operate digital and physical systems, and continuously expand its own capabilities under human
> governance.**

The fundamental loop replaces question→answer:

```
Observe → Understand → Reason → Act → Verify → Learn
```

A chatbot implements *receive text → generate text*. Jarvis treats language as only one interface
to a much larger system.

### 3.2 The six capability pillars (gap estimates as spoken, 2026-07-11)

| # | Pillar | Purpose | Session gap estimate |
|---|--------|---------|---------------------|
| P1 | **Perception** | understand everything happening around the user: cameras, mics, smart home, network, browser, desktop, calendar, email, messages, location, sensors, vehicles, NAS, servers | ~35% complete |
| P2 | **Communication** | interact naturally everywhere: voice, HUD, mobile, Telegram/WhatsApp, email, TV, speakers; cross-device continuity; room & speaker identity; privacy context | ~70–80% |
| P3 | **Action** | actually perform work, on the hierarchy **API → CLI → structured UI automation → visual computer use** (visual is the fallback, never the default) | ~45% |
| P4 | **Environment / House Brain** | the operating system for the house: rooms, occupants, devices, cameras, speakers, displays, climate, lighting, security, presence | ~20% |
| P5 | **Media** | the multimedia director: play music/films/podcasts, choose the right speaker/TV/screen, show webpages/cameras/dashboards, `present(content, target_device, mode, urgency, duration)` | ~15% |
| P6 | **Capability Evolution** | instead of "I can't" → "I don't know **yet**": understand request → search existing skills → research docs/APIs → generate implementation → sandbox test → approval → deploy → reuse forever | ~10% |

Camera work specifically: a local vision pipeline generates structured events (person at the gate,
package left outside, unknown person lingering, child/pet in restricted area, smoke/flood, car
arriving); the LLM inspects images/clips only when an event warrants it — never continuous footage
into a model. Natural-language retrieval ("show me when the courier arrived yesterday") requires
camera-event indexing and temporal retrieval, not just live viewing.

Proactivity requires an event bus, persistent state, temporal reasoning, anomaly detection,
priority scoring, interruption budgets, household routines and escalation policies; for every
event the system decides: **ignore · remember · monitor · act silently · ask for approval ·
interrupt immediately**.

Humor is part of the social behavior model (timing awareness, context, user preferences,
household-safe modes, no repetition, callbacks, confidence thresholds) — not a joke generator.

### 3.3 Target architecture (five layers)

```
┌─────────────────────────────────────────────┐
│              Jarvis Experience              │
│ voice · HUD · mobile · speakers · displays  │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│              Jarvis Cognition               │
│ personal model · house state · specialists  │
│ planning · proactivity · relationship model │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│             Jarvis Action Kernel            │
│ authority · contracts · risk · audit        │
│ approval · budgets · rollback · verification│
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│        Hermes-derived Execution Plane       │
│ browser · terminal · scripts · skills       │
│ subagents · compression · file RPC          │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│               Physical Adapters             │
│ Home Assistant · cameras · media · PCs      │
│ NAS · network · vehicles · sensors          │
└─────────────────────────────────────────────┘
```

Agents become personalities and specialists; **capabilities become the operating system**.

### 3.4 The Capability Registry (the single biggest unlock)

Everything becomes a machine-readable capability; agents reason over the registry instead of
inventing/hardcoding actions:

```yaml
id: media.play
description: Play media on a selected device
inputs: [content, device]
risk: reversible
requires: [media_player]
supports: [spotify, plex, chromecast, airplay]
verification: [playback_started, current_track_matches]
```

Each capability declares: `id · description · inputs · risk · requires · supports · verification ·
rollback · confidence · implementation`. Example ids from the session: `camera.view`,
`camera.detect_person`, `display.open_webpage`, `browser.complete_form`,
`computer.launch_application`, `computer.execute_script`, `home.set_temperature`, `home.lock_door`,
`media.play`, `message.send`, `notification.announce`, `network.restart_device`, `skill.create`,
`skill.test`, `vision.read_screen`.

### 3.5 Graduated autonomy (safety without uselessness)

| Action | Default behavior |
|---|---|
| Read sensor or camera state | Automatic |
| Show a webpage or camera | Automatic |
| Play/pause media | Automatic |
| Adjust lights or temperature | Automatic within learned bounds |
| Run diagnostic scripts | Automatic in sandbox |
| Modify files | Automatic with versioning or backup |
| Send messages externally | Approval or learned recipient policy |
| Purchase, payment, deletion | Explicit approval |
| Unlock doors or disable security | Strong confirmation |
| Install generated skills | Sandbox, test, then approval |

Jarvis gradually **earns** broader authority per capability, device, user and context.

### 3.6 The six new subsystems and the development order

Session names → BACKLOG horizons (**renumbering note:** the conversation proposed these as
"H24–H29"; in this repo ORIZONT 24/25/26 already exist — AI-OS substrate, M1→1.0 execution plan,
"bolt the train" — so the new subsystems land as **ORIZONT 27–33**; do not go looking for H24–H29):

| Session name | Repo horizon | Session phase → version |
|---|---|---|
| Capability Registry + unified Action API + verification framework | **ORIZONT 27** | Phase 1 → v0.21.0 |
| Computer Operator (browser, desktop, scripts, visual fallback) | **ORIZONT 28** | Phase 2 → v0.22.0 |
| Multimedia Director (`present()` fabric) | **ORIZONT 29** | Phase 2 → v0.23.0 |
| House Brain (HA integration, room/device/occupant graph, presence, policies) | **ORIZONT 30** | Phase 3 → v0.24.0 |
| Camera Intelligence / Vision (RTSP/ONVIF, local detection, event index, NL retrieval) | **ORIZONT 31** | Phase 4 → v0.25.0 |
| Capability Acquisition (the self-extension loop) | **ORIZONT 32** | Phase 5 → v0.26.0 |
| Ambient Intelligence (long-running monitors, decision ladder) | **ORIZONT 33** | Phase 6 → v0.27.0 |

## 4. Hermes comparison verdict (as of 2026-07-11)

Reference: `docs/research/2026-06-07-hermes-agent.md` +
`docs/research/2026-07-06-hermes-agent-migration-plan.md` (v3 plan, APPROVED in the Fable handoff §5).

**Where Hermes is ahead (execution maturity):** the closed skill-creation/self-improvement loop;
a mature multi-provider browser stack (CDP, accessibility-tree first, visual fallback, LAN-safe
local routing); portable terminal backends (local/Docker/SSH/cloud); a polished unified
communication gateway; easy install/provider config.

**Where Jarvis is ahead (architecture & governance):** the Action Kernel with contracts, taint
tracking, tamper-evident audit chain, budgets, kill-switch, approval funnels; the personal-world
ontology ambition (people, rooms, devices, vehicles, routines, policies); physical & multimedia
presence; local-first as a non-negotiable rather than an option; persistent domain-specialist
agents.

**Strategy (owner-decided): adopt, don't rebuild — then exceed.**
- Do **not** rebuild Hermes infrastructure feature-by-feature (browser-provider abstraction,
  skill format, context compression, file RPC, terminal backend architecture, subagent delegation,
  session search, gateway patterns). ORIZONT 20 already ports the essential mechanisms under
  Jarvis governance (MIT license vendored, `LICENSES/hermes-agent-MIT.txt`); continue on that lane.
- Spend Jarvis's unique engineering on: Action Kernel & governance, house ontology, capability
  registry, device/room graph, camera intelligence, media presentation, ambient event cortex,
  household permissions, physical outcome verification, long-term personal context.
- **Catch-up list (high priority):** mature browser automation; reusable terminal-target
  abstraction; autonomous procedural skill creation; outcome-based skill refinement; context
  compression (Phase 2 merged in #634); unified cross-platform gateway; easier installation.
- **Do-NOT-copy list:** cloud-first execution as default; unrestricted self-modification; generic
  tool availability without household policy; terminal-centric UX; autonomous browser actions
  outside the Action Kernel; a single general agent replacing persistent domain expertise.
- Hermes could be extended toward a house brain, but it would still lack unified physical-world
  state, household identity/permissions, continuous perception, event correlation over time,
  room-aware output, graded physical authority, local video processing, and low-noise ambient
  autonomy. **Hermes as the hands and learning engine; Jarvis as the brain, policy layer, memory
  system and household model.**

The measurable "superior to Hermes" bar (criteria S1–S8) is defined and maintained in
`AI_OS_VISION.md` §7 — parity-or-better on Hermes's home turf (execution breadth, skill
acquisition, multi-target execution, context endurance) while holding what Hermes doesn't have
(full kernel mediation, local-first proof, the physical-world pillars, governed onboarding).

## 5. Owner decisions (final, 2026-07-11)

1. **The v1.0 gate expands.** 1.0 = the proof track (⭐B0, 72h soak, design partners — unchanged)
   **AND** the AI-OS capability program (ORIZONT 27–33; six pillars at their v1 bar). The owner
   explicitly accepts this pushes 1.0 out by roughly a year.
2. **Goal = the "v3.0 vision" + Hermes.** Superior to Hermes or Hermes integrated into Jarvis:
   Hermes-derived execution plane under a Jarvis-owned cognition/governance/house layer.
3. **This change ships as a strategy/docs PR.** The audit's engineering items become spec'd
   backlog items (H23.24–H23.28), implemented in follow-up PRs.
4. **MOONSHOT.md is rewritten now** as the new north star; the detailed capability vision lives in
   the new root-level `AI_OS_VISION.md`. New strategic docs in English.

## 6. Where it was integrated

- `AI_OS_VISION.md` — the living detailed vision (pillars, architecture, registry, graduated
  autonomy, Hermes superiority bar S1–S8, phase plan, the v1 bar per pillar).
- `MOONSHOT.md` — rewritten §1 statement + loop; §3 thesis #4; §4 trajectory (Phase 2a proven
  core / Phase 2b the AI OS / 1.0 = both); §5 principle #7 (capability growth is governed);
  §6 supporting capability-health signal; §7/§8 doc-map registrations.
- `BACKLOG.md` — Version Roadmap extended v0.21.0–v0.27.0 + the 1.0.0 row redefined; new
  ORIZONT 27–33 sections; H23.24–H23.28; the O26 Phase 6 park-list revised to a phased unpark
  (wave 1 with O28: `browser_agent`/`desktop_operator`/`screen_grounding`; wave 2 with O29:
  `image_gen`/`media_gen`/`media_skill`; wave 3 with O30/O33: `wyoming`/`satellite_hub`/
  `node_mesh`/`e2e_sync`; `training/`+`rust/` stay frozen pending owner pull), gated on the proof
  track milestones (A1 B0 + A2 soak + A7 recruiting started).
- `docs/HISTORY.md` — decision-log row (2026-07-11).
- `README.md` — repositioned lead + softened competitive claims + two-part 1.0 gate.
- Registrations: `CLAUDE.md` routing, `docs/AI_CONTEXT.md` Tier 1, README docs list;
  consistency touches in `GO_LIVE_PLAN.md`, `JARVIS.md`, `STATUS.md`, `docs/OWNER_TASKS.md`,
  `docs/gap-analysis-1.0.md`.
