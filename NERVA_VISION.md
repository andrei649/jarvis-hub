# Nerva — The Personal Intelligence Operating System (product & capability vision)

> Generated: 2026-07-11 · Merged: 2026-07-12 (this document unifies the two parallel vision drafts —
> #661 `docs/NERVA_VISION.md` and #662 `AI_OS_VISION.md` — per the owner's reconciliation decisions;
> the superseded draft is now a pointer stub at [docs/NERVA_VISION.md](docs/NERVA_VISION.md)) ·
> **Owner-approved** · Downstream of [MOONSHOT.md](MOONSHOT.md) §1/§5; upstream of
> [BACKLOG.md](BACKLOG.md) ORIZONT 27–33. When this doc and BACKLOG disagree on priorities,
> **BACKLOG wins** — fix the stale one. Provenance (the full owner session, immutable):
> [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md).
>
> **Naming:** **Nerva** is the end-user product brand (published by **Digitaholic**). `jarvis-hub`
> remains the repository/package codename until the rename is deliberately executed (owner task —
> [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md)). "Jarvis" in older docs refers to this same system.
>
> **How to use this doc:** MOONSHOT.md stays the short north star (why we exist, principles, phase
> gates). This file owns the *product and capability* definition of the destination: the brand
> architecture, the six pillars, the target architecture, the Capability Registry, graduated
> autonomy, and the measurable "superior to Hermes" bar. Read §4 to know what's missing, §9 for the
> build order, §10 for what 1.0 now means.

---

## 1. The statement and the loop

> **Nerva is a local-first Personal Intelligence Operating System that can perceive, understand,
> communicate, operate digital and physical systems, verify outcomes, and continuously expand its
> own capabilities under explicit human governance — owned by the person it serves.**

Nerva is not optimized around question→answer. Its core loop is:

```
Observe → Understand → Decide → Act → Verify → Learn
```

Each verb already has a substrate in this repo — the vision is an *expansion* of what exists, not
a restart:

| Verb | Existing substrate |
|------|--------------------|
| **Observe** | `core/autonomy/observer.py` + watchers, `passive_capture.py`, channels, heartbeat |
| **Understand** | memory fusion (vector ⊕ graph, RRF), bi-temporal KG (H14), ingestion pipeline |
| **Decide** | orchestrator + 17 specialist agents, autonomy policy, `agent_runtime.py` model-directed loop (H20.R1) |
| **Act** | the **Action Kernel** (O24 — Gate-K complete, 11 action kinds mediated), brokers, ToolRPC, sandbox |
| **Verify** | the **Verification Fabric** (O24 — reality harness, SEAM→WIRED→VERIFIED→GA registry) |
| **Learn** | the governed per-turn learning loop (O20 — `learning/background_review.py`, CoreMemory, skill curator) |

A chatbot implements *receive text → generate text*. Nerva treats language as only one interface
to a much larger system: a persistent intelligence layer across the user's computers, browser,
media, communications, home, cameras, devices, vehicles, projects, family context and external
events. This does **not** replace the MOONSHOT bet — local-first, governed, owned — it states what
the machine must be *able to do* while honoring it.

## 2. Brand architecture

- **Digitaholic** — company and publisher.
- **Nerva** — end-user product and primary identity.
- **Cortex** — cognition: reasoning, planning, memory, orchestration, autonomy, agent coordination.
- **Atlas** — reality model and infrastructure: WorldView, Signal Layer, geospatial intelligence,
  world events, house model, rooms, devices, vehicles, distributed nodes, servers and synchronization.
- **Synapse** — capabilities and learning: Capability Registry, skills, tools, connectors,
  discovery, generation, testing, promotion and reuse.
- **Vision** — visual perception: cameras, images, OCR, video understanding, surveillance events
  and visual computer use.
- **Ultron** — security and governance: Action Kernel, policies, contracts, permissions, taint,
  approval, audit, budgets and kill switches.
- **Howard** — personal identity and digital twin: voice, style, personal RAG, preference model
  and user-specific adaptation.
- **Frigga** — family intelligence: people, routines, care context and strict-local family memory.
- **Argus** — external intelligence role operating through Atlas: OSINT, geospatial monitoring and
  governed situational awareness.

The user should experience **one coherent system — Nerva** — rather than a collection of unrelated
chatbots. Existing named agents remain as specialist roles, personalities or internal services.

**Atlas is not merely cluster infrastructure. It is Nerva's model of reality:**

```
Atlas
├── WorldView — 3D/4D map, time, geospatial layers, air/sea/space/cyber
├── Signal Layer — evidence, events, signals, assessments and briefs
├── External world — weather, traffic, markets, incidents, news and OSINT
├── House model — properties, floors, rooms, zones, occupants and policies
├── Device graph — PCs, servers, Pi nodes, NAS, routers, TVs, speakers and sensors
├── Vehicle model — location, status, maintenance and telemetry
└── Execution topology — local, Docker, SSH, edge and optional cloud targets
```

Atlas provides the shared state against which Cortex reasons. **Vision observes. Atlas locates and
contextualizes. Cortex decides. Synapse supplies the capability. Ultron authorizes. Nerva executes
and verifies.**

## 3. Honest baseline (2026-07-11)

- **v0.11.0**, feature-complete + refactored; test/route counts are auto-synced in
  [STATUS.md](STATUS.md) (never trust hand-written numbers elsewhere).
- **Ultron / Gate-K complete**: every one of the 11 privileged action kinds crosses
  `kernel.authorize` (action-auth snapshot has zero `pending`).
- **Synapse seeds — ORIZONT 20 (Hermes Mining) 6/6 + live wave**: the governed per-turn learning
  loop is merged (default-off), skill lifecycle + curator live, ToolRPC spine + execution
  environments (local/docker/ssh) merged.
- **H15 computer-use**: governance complete (egress allowlist, approval queue, injection defense,
  a11y fusion) but **actuation is stubbed** — `NullBrowserDriver`/`NullDesktopDriver`; no real
  Playwright/VM driver in-repo.
- **Media**: Spotify control is real; there is **no** Chromecast / `media_player` abstraction.
- **House (Atlas)**: Homebridge + Tuya + Wyoming voice satellite exist; there is **no** Home
  Assistant state API integration and no room/occupant/device graph. WorldView + Signal Layer are
  substantial but not yet unified with house/device/execution state.
- **Cameras (Vision)**: nothing exists (no RTSP/ONVIF/Frigate code anywhere).
- **Proof**: single-user; ⭐B0 manual run, 72h soak and design partners still pending (the proof
  track — unchanged, see §10).

## 4. The six capability pillars

Format per pillar: *what it means → what exists (honest, file-level) → what's missing → which
horizon closes it*. Gap percentages are the owner-session estimates (2026-07-11), kept as honest
orientation, not measurements. Sub-brand owner in parentheses.

### P1 — Perception (~35%) — Vision + Atlas

*Understand everything happening around the user: cameras, mics, smart home, network, browser,
desktop, calendar, email, messages, sensors, vehicles, NAS, servers. Continuous raw streams are
converted **locally** into structured events; expensive model inspection happens only when an
event, query or policy requires it.*

- **Exists:** voice pipeline (`core/voice/` — wake word, STT), VLM eyes (`llm/vlm.py`,
  `/api/vlm/describe`), screen grounding (`screen_grounding.py`), opt-in passive capture,
  7-phase ingestion pipeline, host observer (`autonomy/observer.py`), channel inbounds.
- **Missing:** cameras entirely; house sensor streams; vehicle telemetry; continuous ambient
  observation with event correlation over time; desktop observation as a routine perception source.
- **Closed by:** ORIZONT 31 (cameras), ORIZONT 30 (house sensors/presence), ORIZONT 33 (ambient).

### P2 — Communication (~70–80%) — the Nerva experience

*Interact naturally everywhere; conversation continuity across channels and devices; know who is
speaking, where, and how private the context is; deliver on the right surface (speaker, display,
phone, headphones) for the person, room, privacy and urgency.*

- **Exists:** web SSE, voice, Telegram, Discord, email, Slack; `channels/session.py` +
  `gateway.py`; channel inbox transport v0; interrupt budgets (≤4 push/day); Wyoming satellite
  protocol for room voice endpoints.
- **Missing:** presence-aware delivery; speaker/room identity; media surfaces (TV, speakers,
  displays) as first-class output channels; ambient vs private delivery decisions. **Personality
  and humour as social policy** — contextual humour with callbacks, household-safe modes,
  user-specific tone and timing, no repetitive or forced jokes, the ability to shift between
  concise operational mode and richer conversational mode (a persistent companion, not a command
  shell — and not a standalone joke generator).
- **Closed by:** ORIZONT 29 (output routing / `present()`), ORIZONT 30 (room context),
  ORIZONT 33 (delivery ladder); personality depth rides the existing cognition/persona lane (O21).

### P3 — Action (~45%) — Synapse + Ultron

*Actually perform work, on the hierarchy* **API → CLI/script → structured browser/accessibility
automation → visual mouse/keyboard fallback** *(visual is the fallback, never the default), with
post-action verification and rollback where possible.*

- **Exists:** the Action Kernel (O24) with contracts (`automation_contracts.py`), budgets,
  kill-switch, audit chain; write-back + connector builders (~27 SaaS actions); ToolRPC
  (`tool_rpc.py`) + the model-directed tool loop (`agent_runtime.py`, default-off); execution
  environments local/docker/ssh; sandbox with output caps; governed browser/desktop **policy**
  layers (H15).
- **Missing:** real browser/desktop actuation (the drivers are Null host-seams); the action
  hierarchy as an explicit router that picks the lowest-risk implementation; a single unified
  call path (`perform(capability, params)`) instead of per-surface broker wiring.
- **Closed by:** ORIZONT 27 (unified Action API), ORIZONT 28 (real operators).

### P4 — Environment / House Brain (~20%) — Atlas

*The operating system for the house: properties, floors, rooms, zones, occupants, guests and
permissions; sensors, cameras, displays, speakers and actuators; routines, presence and temporal
patterns; climate, lighting, energy, security and media; household privacy and interruption
policies.*

- **Exists:** `plugins/homebridge.py` (HomeKit accessories, LOCAL_ONLY), `plugins/iot_control.py`
  (Tuya, partly mock), `voice/wyoming.py` (HA Voice PE satellites); the bi-temporal KG as the
  natural home for the house graph; WorldView/Signal Layer as Atlas's external-world half.
- **Missing:** Home Assistant REST/WebSocket **state** integration; the device/room/occupant
  graph; presence & context inference; household policies (privacy zones, per-person authority).
- **Closed by:** ORIZONT 30. Home Assistant/Homebridge provide device abstraction, but **Nerva
  owns reasoning, memory, policy, natural interaction and cross-domain coordination**.

### P5 — Media (~15%) — the presentation fabric

*The multimedia director: play, pause, seek and route music, film, podcasts and radio; choose the
correct TV, speaker or display; show webpages, maps, dashboards and camera feeds; move media
between rooms; create temporary interactive visual surfaces; present private information only on
appropriate devices. One verb:*

```
present(content, target, mode, privacy, urgency, duration)
```

- **Exists:** real Spotify control (`plugins/spotify_plugin.py` — OAuth, playback, devices);
  generated-media catalog/exports (`media_catalog.py`, `media_gen.py`).
- **Missing:** a `media_player` abstraction and device registry (Chromecast, AirPlay, TVs,
  browser-tab kiosk, local players); the `present()` capability itself; content resolvers;
  media-session etiquette (don't interrupt a movie for a P3 nudge); cross-room media movement.
- **Closed by:** ORIZONT 29.

### P6 — Capability Evolution (~10%) — Synapse

*Instead of "I can't" → "I don't know **yet**": understand the intended outcome → search the
Capability Registry → inspect available tools, APIs, devices and documentation → produce a bounded
implementation plan → generate a temporary skill or adapter → test it in isolation → verify
read-only behavior first → request approval according to risk → execute and verify the real
outcome → promote the validated capability for reuse.*

- **Exists:** the full skill lifecycle (loader, importer, usage telemetry, nightly curator,
  proposals, signing, marketplace with rollback); `self_evolution.py` (governed prompt
  optimization); the per-turn learning loop (O20.L — facts + skill patches distilled under
  governance); sandbox + quarantine.
- **Missing:** the **closed acquisition loop** above, end-to-end. Generated capabilities never
  bypass Synapse validation or Ultron governance.
- **Closed by:** ORIZONT 32 (loop) + ORIZONT 27 (the registry it feeds).

## 5. Target architecture

```
┌─────────────────────────────────────────────┐
│              Nerva Experience               │
│ voice · HUD · mobile · speakers · displays  │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│           Cortex (+ Atlas state)            │
│ personal model · house state · specialists  │
│ planning · proactivity · relationship model │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│         Ultron — the Action Kernel          │
│ authority · contracts · risk · audit        │
│ approval · budgets · rollback · verification│
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│   Synapse — Hermes-derived Execution Plane  │
│ browser · terminal · scripts · skills       │
│ subagents · compression · file RPC          │
└──────────────────────┬──────────────────────┘
┌──────────────────────▼──────────────────────┐
│         Physical Adapters (Atlas edge)      │
│ Home Assistant · cameras · media · PCs      │
│ NAS · network · vehicles · sensors          │
└─────────────────────────────────────────────┘
```

Layer → repo mapping: **Experience** = channels/HUD/voice/mobile (exists). **Cortex/Atlas** =
memory fusion + bi-temporal KG + cognition layer + the 17 specialists + autonomy stack (exists;
house state is new, O30; WorldView/Signal Layer fold in as Atlas's external half). **Ultron** =
O24 (exists; the boundary). **Synapse execution plane** = O20/H20 ToolRPC + environments + skills +
subagents (exists; operators land in O28). **Physical Adapters** = O29/O30/O31 (mostly new).

**The kernel is the boundary:** nothing from the execution plane touches a physical adapter
without crossing `kernel.authorize`. Agents become personalities and specialists; **capabilities
become the operating system.**

## 6. The Capability Registry (the single biggest unlock)

A machine-readable inventory of everything Nerva can do, owned by Synapse. Agents reason over it
instead of hardcoding actions; the planner selects capabilities by description/inputs/risk/
confidence and refuses honestly when nothing matches.

```yaml
id: media.play
description: Play selected media on a target device
inputs:
  content: media reference or natural-language query
  target: device, room or audience
risk: reversible               # kernel risk tier
requires: [media_player]       # contract / dependency
implementations:               # binding — plugin / skill / broker / route-tool
  - spotify
  - chromecast
verification:                  # V1 reality-harness case that proves it
  - target reports playing
  - active item matches requested content
rollback:                      # machine-readable undo story
  - restore previous playback state
confidence: 0.92               # earned from outcome stats
```

Minimum capability families: `browser.*` · `computer.*` · `script.*` · `file.*` · `message.*` ·
`media.*` · `display.*` · `home.*` · `camera.*` · `network.*` · `vehicle.*` · `world.*` · `skill.*`.
**Capabilities, not agent names, become the stable execution interface.**

**This extends ORIZONT 24 — it does not rival it.** The mapping is explicit so no one builds a
parallel system:

| Registry field | Existing substrate it extends |
|---|---|
| verification state | V2 `observability/capability_registry.py` — `CapabilityRecord` + SEAM→WIRED→VERIFIED→GA (only the V1 reality harness promotes to VERIFIED) |
| requires / policy | `automation_contracts.py` `ContractTemplate`s (payment/social/writeback/call/A2A precedents) |
| risk + mediation | the action-auth matrix (`tests/test_action_auth_matrix.py` + `_snapshots/action_auth.json`) — the ground truth that an action kind is kernel-mediated |
| confidence | `skills/usage.py`-style outcome telemetry, generalized per capability (H27.7) |
| implementations | plugins (`plugin_gate.BUILTIN_PLUGINS`), skills, brokers, MCP route tools |

The **unified Action API** (H27.3) is the single call path: `perform(capability_id, params, ctx)`
→ registry lookup → contract check → `kernel.authorize` → implementation → verification.

## 7. Graduated autonomy (safety without uselessness)

Nerva must be powerful without requiring approval for every harmless action — and ungoverned
autonomy is the OpenClaw failure mode. The answer is **earned, per-capability authority**: the
kernel's GRANT/QUEUE verdicts move as confidence is earned, within hard floors that never move.
Authority is scoped by user, capability, device, target, location, time and context; every
meaningful action is auditable and outcome-verified.

| Capability (example) | Default | Earned ceiling | Mechanism |
|---|---|---|---|
| Read sensors, state and public data | auto | auto | kernel GRANT (read-only tier) |
| Show content / camera feeds / dashboards | auto within privacy rules | auto | `present()` reversible tier + room privacy policy |
| Play / pause media | auto | auto | reversible; media-session etiquette (H29.4) |
| Adjust lights / climate | ask | auto within learned bounds | contract bounds + H27.7 confidence |
| Run diagnostic scripts | auto in sandbox | auto in sandbox | sandbox + output caps (never on host by default) |
| Modify files | ask | auto with versioning/backup first | rollback contract required (H27.6) |
| Browser read / research | auto | auto | egress allowlist (H15) |
| Browser write (forms, submissions) | ask | learned per-site policy | GovernedBrowser approval queue |
| Send messages externally | ask | learned recipient policy | contracts + sender pairing |
| Host terminal / OS control | ask | ask | GovernedDesktop; per-target policy (H28.3) |
| Install a generated skill | sandbox → tests → approval | same | O32 loop; quarantine before promotion |
| Purchase / payment / destructive deletion / security disablement | explicit strong approval | **never above QUEUE** | `IRREVERSIBLE_OR_MONEY` — hard floor |
| Unlock doors / expose private video | strong identity + context verification | **never above QUEUE** | hard floor (H30.4/H31.1); no confidence path exists |
| Any cloud hop | opt-in | opt-in | MOONSHOT §5.2 — principle, not policy |
| Anything touching untrusted external data | escalated | escalated | taint GRANT→QUEUE (P2 precedent) |

Two invariants (from the O20 review, now general): the review/learning model is strict-local by
construction, and every self-modification lands in quarantine/approval — never direct.

## 8. The Hermes strategy — integrate, then exceed

Reference research: [2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md) ·
[2026-07-06-hermes-agent-migration-plan.md](docs/research/2026-07-06-hermes-agent-migration-plan.md)
(APPROVED) · the 2026-07-11 session archive.

**Verdict.** Hermes Agent is ahead on execution maturity: the closed skill-creation loop, a mature
multi-provider browser stack, portable terminal backends, gateway polish. Nerva is ahead on
governance (Action Kernel, contracts, taint, tamper-evident audit), the personal-world ontology
(Atlas), physical/multimedia presence, and local-first as a non-negotiable. **Hermes-derived
components are hands and procedural learning. Nerva remains the brain, identity, policy layer and
house operating model.**

**Strategy.** Do **not** rebuild Hermes feature-by-feature. Adopt its mechanisms under Nerva
governance — ORIZONT 20 is the precedent and the lane (MIT, vendored at
`LICENSES/hermes-agent-MIT.txt`); wire the remaining primitives (file-RPC transports, gateway
session model, cron) when a real consumer appears. Spend unique engineering where Hermes has
nothing: kernel, registry, house, cameras, media, ambient autonomy.

- **Catch-up list (high priority):** mature browser automation · terminal-target abstraction ·
  autonomous skill creation · outcome-based skill refinement · context compression (Phase 2
  merged, #634) · unified gateway · easier install.
- **Do-NOT-copy list:** cloud-first execution defaults · unrestricted self-modification · generic
  tool availability without household policy · terminal-centric UX · browser actions outside the
  Action Kernel · one general agent instead of persistent domain specialists.

### The superiority bar (S1–S8) — measured, never asserted

> **"Superior to Hermes" = parity-or-better on S1–S4 (its home turf) while holding S5–S8 (ours)
> — each proven by a harness artifact, not a claim.**

| # | Criterion | Bar | Evidence artifact |
|---|-----------|-----|-------------------|
| S1 | Execution breadth | ≥ parity on a defined 20-task browser/computer benchmark, **kernel ON** (zero ungoverned actions in the trace) | operator reality-harness pack (H28.5) |
| S2 | Skill acquisition | acquire → sandbox-verify → approve → register a net-new skill end-to-end; reuse-before-generate rate measured | O32 loop + H32.7 parity eval |
| S3 | Multi-target execution | local/docker/ssh targets with per-target policy **and** audit chain (Hermes has backends, not the audit) | H28.3 |
| S4 | Context endurance | compression keeps eval-suite success ≥95% of uncompressed | eval lane on the merged compressor |
| S5 | Governance (must hold while matching S1–S4) | 100% privileged actions kernel-mediated (action-auth snapshot zero-pending) · taint escalation live · audit `verify_chain` green | existing O24 gates |
| S6 | Local-first proof | the full loop with **zero external calls** in LOCAL_ONLY posture | H23.16 network monitor `clean=True` |
| S7 | Personal-world moat | VERIFIED capabilities on pillars P4–P6 (house, media, acquisition) where Hermes has none | V2 registry states |
| S8 | Time-to-first-governed-action | fresh install → first accepted autonomous action < 30 min | command-center funnel (T-0.19) |

## 9. Development order — Programs ↔ Horizons

Phases from the owner session, mapped to the #661 delivery programs, BACKLOG horizons and minors.
**The proof track (0.12–0.20, ⭐B0, 72h soak, design partners) runs in parallel from day 1 and is
not displaced** — it is the other half of the 1.0 gate (§10). Capability horizons unpark their
frozen modules per the revised park-list policy (BACKLOG → ORIZONT 26 Phase 6).

| Phase | Program (#661) | Horizon | Version | Builds on (don't rebuild) |
|---|---|---|---|---|
| 1 | **A — Foundations** | **O27 Capability Registry & Unified Action API** (+ O24 K/V; execution-target inventory lands as H28.3) | v0.21.0 | O24 V2 registry, `automation_contracts.py`, action-auth matrix, `agent_runtime.py` |
| 2a | **B — Computer operator** | **O28 Computer & Browser Operator** | v0.22.0 | H15 governed stubs, `core/environments/`, ToolRPC |
| 2b | **C — Media and surfaces** | **O29 Multimedia Director** | v0.23.0 | `spotify_plugin.py`, `media_catalog.py`, interrupt budgets |
| 3 | **D — Atlas house model** | **O30 House Brain** | v0.24.0 | homebridge/iot plugins, Wyoming, bi-temporal KG, WorldView/Signal Layer |
| 4 | **E — Vision and surveillance** | **O31 Camera Intelligence** | v0.25.0 | greenfield; `llm/vlm.py` for description; privacy contract first |
| 5 | **F — Synapse self-extension** | **O32 Capability Acquisition** | v0.26.0 | O20 learning loop, skill lifecycle, sandbox, `grounded_plan.py` |
| 6 | **G — Ambient cognition** | **O33 Ambient Intelligence** | v0.27.0 | `autonomy/observer.py`, watchers, policy, night-shift |

Order can adapt to reality (a design partner's need may pull O29 before O28); **gates cannot be
skipped** (MOONSHOT §4).

## 10. What this changes about v1.0

**Decision (owner, 2026-07-11, reconfirmed 2026-07-12):** the 1.0 gate expands. The "v3.0 vision"
is pulled **into** 1.0 — explicitly, so there is no ambiguity about scope. *(This supersedes the
narrower "v1.0 remains productionized + proven, plus one vertical slice per pillar" staging in the
#661 draft — the vertical slices below are the per-pillar v1 bar, and they are part of the gate,
not a preview of it.)*

> **1.0 = (a) the proof track complete AND (b) all six pillars at their v1 bar.**

**(a) Proof track — unchanged:** the H23 spine + O24–O26 program; ⭐B0 governed-autonomy manual
run; 72h unattended soak; 1–3 design partners running a non-owner install ≥2 weeks with real
north-star data; owner legal/brand (license flip, GitHub settings); manual-test/audit pass tags
the version. A stranger can install, understand and trust the system; first-run success and
backup/restore hold.

**(b) The v1 bar per pillar (VERIFIED via the reality harness, not asserted):**

| Pillar | v1 bar |
|---|---|
| P1 Perception | camera events + house sensor state flowing into memory with retention/consent controls |
| P2 Communication | presence-aware delivery on ≥2 output surfaces beyond chat (e.g. speaker + display) |
| P3 Action | real browser + desktop operator behind the kernel; the API→CLI→UI→visual router picks the lowest-risk path |
| P4 House | HA state + device/room/occupant graph + governed actuation (locks/doors never below strong confirmation) |
| P5 Media | `present()` on ≥2 device classes with session etiquette |
| P6 Evolution | one full acquisition loop (gap → research → generate → sandbox → approve → registry → reuse) demonstrated under approval |

**Post-1.0 staging keeps its meaning** (depth beyond the v1 bar — the former #661 v2/v3 content):
**v1.x — house & ambient depth:** complete room/device/occupant graph, richer media routing, local
camera event intelligence at scale, presence-aware proactive routines, distributed Atlas nodes,
stronger mobile/voice continuity, household identity and permissions. **v2.0-class — ecosystem:**
multi-user/households, moderated marketplace, hosted tier (MOONSHOT §4 Phase 3, unchanged). Mature
computer operation, autonomous acquisition and long-running ambient reasoning keep deepening
continuously — the v1 bar is the first provable slice of each, not the ceiling. The owner accepts
that the expanded gate moves 1.0 out by roughly a year.

## 11. Definition of success

Nerva is succeeding when it can repeatedly demonstrate scenarios such as:

- detect a delivery, show the correct camera on the nearest screen, remember the event and notify
  only the relevant person;
- understand that a child is sleeping, move media to another room and lower volume without being
  asked twice;
- research an unsupported device, build and test a connector, request bounded approval and retain
  the capability;
- operate a browser or desktop application, verify the result and recover safely from failure;
- monitor house, network, NAS and cameras continuously without producing notification noise;
- coordinate information from WorldView, local sensors, calendars and personal priorities into one
  useful decision.

The product is not complete because it can answer anything. It is complete when it can
**understand context, act safely across systems, verify reality and become more capable over time**.

## 12. Risks and honest constraints

- **Scope-gravity is the #1 risk** (the year-one review's warning stands). Mitigation: the phase
  gates above; the proof track runs first and in parallel; the park-list guard (H23.28) gets
  implemented, not just described; one horizon in flight at a time.
- **Actuation needs the owner's hardware.** Browser/desktop drivers, HA, cameras, media devices
  are host seams — engineering can build the governed rails and hermetic harnesses; only the box
  proves them live.
- **Cameras are privacy-critical.** H31.1 (frames never leave the box; household consent;
  kill-switch coverage; retention defaults; privacy masks) precedes any frame processing — it is
  deliberately the first item of ORIZONT 31.
- **The north-star + counter-metrics stay the drift guard** (MOONSHOT §6 unchanged): if interrupt
  rate, reject rate, %-local or p95 degrade while capabilities grow, the program is failing even
  if features ship.

## 13. Doc relationships

| Question | Doc |
|---|---|
| Why we exist, principles, phase gates | [MOONSHOT.md](MOONSHOT.md) |
| What is Nerva / what can it do / what's missing / the Hermes bar | **this file** |
| What to build next, prioritized | [BACKLOG.md](BACKLOG.md) (wins on priorities) |
| Where the strategy came from | [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md) (immutable) |
| What only the owner can do (incl. the jarvis-hub→Nerva rename) | [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md) |
