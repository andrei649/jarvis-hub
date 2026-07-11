# Jarvis — The Personal AI Operating System (capability vision)

> Generated: 2026-07-11 · **Owner-approved** · Downstream of [MOONSHOT.md](MOONSHOT.md) §1/§5;
> upstream of [BACKLOG.md](BACKLOG.md) ORIZONT 27–33. When this doc and BACKLOG disagree on
> priorities, **BACKLOG wins** — fix the stale one. Provenance (the full owner session, immutable):
> [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md).
>
> **How to use this doc:** MOONSHOT.md stays the short north star (why we exist, principles,
> phase gates). This file owns the *capability* definition of the destination: the six pillars,
> the target architecture, the Capability Registry, graduated autonomy, and the measurable
> "superior to Hermes" bar. Read §3 to know what's missing, §8 for the build order, §9 for what
> 1.0 now means.

---

## 1. The statement and the loop

> **Jarvis is a local-first Personal AI Operating System that can perceive, reason, communicate,
> operate digital and physical systems, and continuously expand its own capabilities under human
> governance.**

The fundamental loop replaces question→answer:

```
Observe → Understand → Reason → Act → Verify → Learn
```

Each verb already has a substrate in this repo — the vision is an *expansion* of what exists, not
a restart:

| Verb | Existing substrate |
|------|--------------------|
| **Observe** | `core/autonomy/observer.py` + watchers, `passive_capture.py`, channels, heartbeat |
| **Understand** | memory fusion (vector ⊕ graph, RRF), bi-temporal KG (H14), ingestion pipeline |
| **Reason** | orchestrator + 17 specialist agents, `agent_runtime.py` model-directed loop (H20.R1) |
| **Act** | the **Action Kernel** (O24 — Gate-K complete, 11 action kinds mediated), brokers, ToolRPC, sandbox |
| **Verify** | the **Verification Fabric** (O24 — reality harness, SEAM→WIRED→VERIFIED→GA registry) |
| **Learn** | the governed per-turn learning loop (O20 — `learning/background_review.py`, CoreMemory, skill curator) |

A chatbot implements *receive text → generate text*. Jarvis treats language as only one interface
to a much larger system. This does **not** replace the MOONSHOT bet — local-first, governed,
owned — it states what the machine must be *able to do* while honoring it.

## 2. Honest baseline (2026-07-11)

- **v0.11.0**, feature-complete + refactored; test/route counts are auto-synced in
  [STATUS.md](STATUS.md) (never trust hand-written numbers elsewhere).
- **Gate-K complete**: every one of the 11 privileged action kinds crosses `kernel.authorize`
  (action-auth snapshot has zero `pending`).
- **ORIZONT 20 (Hermes Mining) 6/6 + live wave**: the governed per-turn learning loop is merged
  (default-off), skill lifecycle + curator live, ToolRPC spine + execution environments
  (local/docker/ssh) merged.
- **H15 computer-use**: governance complete (egress allowlist, approval queue, injection defense,
  a11y fusion) but **actuation is stubbed** — `NullBrowserDriver`/`NullDesktopDriver`; no real
  Playwright/VM driver in-repo.
- **Media**: Spotify control is real; there is **no** Chromecast / `media_player` abstraction.
- **House**: Homebridge + Tuya + Wyoming voice satellite exist; there is **no** Home Assistant
  state API integration and no room/occupant/device graph.
- **Cameras**: nothing exists (no RTSP/ONVIF/Frigate code anywhere).
- **Proof**: single-user; ⭐B0 manual run, 72h soak and design partners still pending (the proof
  track — unchanged, see §9).

## 3. The six capability pillars

Format per pillar: *what it means → what exists (honest, file-level) → what's missing → which
horizon closes it*. Gap percentages are the owner-session estimates (2026-07-11), kept as honest
orientation, not measurements.

### P1 — Perception (~35%)

*Understand everything happening around the user: cameras, mics, smart home, network, browser,
desktop, calendar, email, messages, sensors, vehicles, NAS, servers.*

- **Exists:** voice pipeline (`core/voice/` — wake word, STT), VLM eyes (`llm/vlm.py`,
  `/api/vlm/describe`), screen grounding (`screen_grounding.py`), opt-in passive capture,
  7-phase ingestion pipeline, host observer (`autonomy/observer.py`), channel inbounds.
- **Missing:** cameras entirely; house sensor streams; continuous ambient observation with
  event correlation over time; desktop observation as a routine perception source.
- **Closed by:** ORIZONT 31 (cameras), ORIZONT 30 (house sensors/presence), ORIZONT 33 (ambient).

### P2 — Communication (~70–80%)

*Interact naturally everywhere; conversation continuity across devices; know who is speaking,
where, and how private the context is.*

- **Exists:** web SSE, voice, Telegram, Discord, email, Slack; `channels/session.py` +
  `gateway.py`; channel inbox transport v0; interrupt budgets (≤4 push/day); Wyoming satellite
  protocol for room voice endpoints.
- **Missing:** presence-aware delivery (right device, right room, right urgency); speaker/room
  identity; media surfaces (TV, speakers, displays) as first-class output channels; ambient vs
  private delivery decisions.
- **Closed by:** ORIZONT 29 (output routing / `present()`), ORIZONT 30 (room context),
  ORIZONT 33 (delivery ladder).

### P3 — Action (~45%)

*Actually perform work, on the hierarchy* **API → CLI → structured UI automation → visual
computer use** *(visual is the fallback, never the default).*

- **Exists:** the Action Kernel (O24) with contracts (`automation_contracts.py`), budgets,
  kill-switch, audit chain; write-back + connector builders (~27 SaaS actions); ToolRPC
  (`tool_rpc.py`) + the model-directed tool loop (`agent_runtime.py`, default-off); execution
  environments local/docker/ssh; sandbox with output caps; governed browser/desktop **policy**
  layers (H15).
- **Missing:** real browser/desktop actuation (the drivers are Null host-seams); the action
  hierarchy as an explicit router that picks the lowest-risk implementation; a single unified
  call path (`perform(capability, params)`) instead of per-surface broker wiring.
- **Closed by:** ORIZONT 27 (unified Action API), ORIZONT 28 (real operators).

### P4 — Environment / House Brain (~20%)

*The operating system for the house: rooms, occupants, devices, cameras, speakers, displays,
climate, lighting, security, presence, policies.*

- **Exists:** `plugins/homebridge.py` (HomeKit accessories, LOCAL_ONLY), `plugins/iot_control.py`
  (Tuya, partly mock), `voice/wyoming.py` (HA Voice PE satellites); the bi-temporal KG as the
  natural home for a house graph.
- **Missing:** Home Assistant REST/WebSocket **state** integration; the device/room/occupant
  graph; presence & context inference; household policies (privacy zones, per-person authority).
- **Closed by:** ORIZONT 30. Home Assistant is the intended device abstraction layer; Jarvis
  sits above it as the reasoning and authority layer.

### P5 — Media (~15%)

*The multimedia director: play the right thing on the right device; show webpages, cameras,
dashboards; one verb —* `present(content, target_device, mode, urgency, duration)`.

- **Exists:** real Spotify control (`plugins/spotify_plugin.py` — OAuth, playback, devices);
  generated-media catalog/exports (`media_catalog.py`, `media_gen.py`).
- **Missing:** a `media_player` abstraction and device registry (Chromecast, AirPlay, TVs,
  browser-tab kiosk, local players); the `present()` capability itself; content resolvers;
  media-session etiquette (don't interrupt a movie for a P3 nudge).
- **Closed by:** ORIZONT 29.

### P6 — Capability Evolution (~10%)

*Instead of "I can't" → "I don't know **yet**": understand the gap → search existing skills →
research docs/APIs → generate → sandbox test → approval → registry → reuse forever.*

- **Exists:** the full skill lifecycle (loader, importer, usage telemetry, nightly curator,
  proposals, signing, marketplace with rollback); `self_evolution.py` (governed prompt
  optimization); the per-turn learning loop (O20.L — facts + skill patches distilled under
  governance); sandbox + quarantine.
- **Missing:** the **closed acquisition loop** — gap detection, reuse-first search, doc research,
  generation with a mandatory verification test, approval → registry entry at low confidence,
  autonomy earned over time.
- **Closed by:** ORIZONT 32 (loop) + ORIZONT 27 (the registry it feeds).

## 4. Target architecture

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

Layer → repo mapping: **Experience** = channels/HUD/voice/mobile (exists). **Cognition** = memory
fusion + bi-temporal KG + cognition layer + the 17 specialists + autonomy stack (exists; house
state is new, O30). **Action Kernel** = O24 (exists; the boundary). **Execution Plane** =
O20/H20 ToolRPC + environments + skills + subagents (exists; operators land in O28). **Physical
Adapters** = O29/O30/O31 (mostly new).

**The kernel is the boundary:** nothing from the execution plane touches a physical adapter
without crossing `kernel.authorize`. Agents become personalities and specialists; **capabilities
become the operating system.**

## 5. The Capability Registry (the single biggest unlock)

A machine-readable inventory of everything Jarvis can do. Agents reason over it instead of
hardcoding actions; the planner selects capabilities by description/inputs/risk/confidence and
refuses honestly when nothing matches.

```yaml
id: media.play
description: Play media on a selected device
inputs: [content, device]
risk: reversible          # kernel risk tier
requires: [media_player]  # contract / dependency
supports: [spotify, chromecast, airplay]
verification: reality-case id   # V1 harness case that proves it
rollback: media.pause           # machine-readable undo story
confidence: 0.92                # earned from outcome stats
implementation: plugin:spotify  # binding — plugin / skill / broker / route-tool
```

**This extends ORIZONT 24 — it does not rival it.** The mapping is explicit so no one builds a
parallel system:

| Registry field | Existing substrate it extends |
|---|---|
| verification state | V2 `observability/capability_registry.py` — `CapabilityRecord` + SEAM→WIRED→VERIFIED→GA (only the V1 reality harness promotes to VERIFIED) |
| requires / policy | `automation_contracts.py` `ContractTemplate`s (payment/social/writeback/call/A2A precedents) |
| risk + mediation | the action-auth matrix (`tests/test_action_auth_matrix.py` + `_snapshots/action_auth.json`) — the ground truth that an action kind is kernel-mediated |
| confidence | `skills/usage.py`-style outcome telemetry, generalized per capability (H27.7) |
| implementation | plugins (`plugin_gate.BUILTIN_PLUGINS`), skills, brokers, MCP route tools |

The **unified Action API** (H27.3) is the single call path: `perform(capability_id, params, ctx)`
→ registry lookup → contract check → `kernel.authorize` → implementation → verification. Example
capability ids the registry grows toward: `camera.view`, `camera.detect_person`,
`display.open_webpage`, `browser.complete_form`, `computer.execute_script`, `home.set_temperature`,
`home.lock_door`, `media.play`, `message.send`, `notification.announce`, `network.restart_device`,
`skill.create`, `skill.test`, `vision.read_screen`.

## 6. Graduated autonomy (safety without uselessness)

Blanket restriction makes the system useless; ungoverned autonomy makes it OpenClaw. The answer is
**earned, per-capability authority** — the kernel's GRANT/QUEUE verdicts move as confidence is
earned, within hard floors that never move.

| Capability (example) | Default | Earned ceiling | Mechanism |
|---|---|---|---|
| Read sensor / house / camera state | auto (after household consent for cameras) | auto | kernel GRANT (read-only tier) |
| Show a webpage / camera / dashboard | auto | auto | `present()` reversible tier |
| Play / pause media | auto | auto | reversible; media-session etiquette (H29.4) |
| Adjust lights / temperature | ask | auto within learned bounds | contract bounds + H27.7 confidence |
| Run diagnostic scripts | auto in sandbox | auto in sandbox | sandbox + output caps (never on host by default) |
| Modify files | ask | auto with versioning/backup | rollback contract required (H27.6) |
| Browser read / research | auto | auto | egress allowlist (H15) |
| Browser write (forms, purchases-adjacent) | ask | learned per-site policy | GovernedBrowser approval queue |
| Send messages externally | ask | learned recipient policy | contracts + sender pairing |
| Host terminal / OS control | ask | ask | GovernedDesktop; per-target policy (H28.3) |
| Purchase / payment / deletion | explicit approval | **never above QUEUE** | `IRREVERSIBLE_OR_MONEY` — hard floor |
| Unlock doors / disable security | strong confirmation | **never above QUEUE** | hard floor (H30.4); no confidence path exists |
| Install a generated skill | sandbox → test → approval | same | O32 loop; quarantine before promotion |
| Any cloud hop | opt-in | opt-in | MOONSHOT §5.2 — principle, not policy |
| Anything touching untrusted external data | escalated | escalated | taint GRANT→QUEUE (P2 precedent) |

Two invariants (from the O20 review, now general): the review/learning model is strict-local by
construction, and every self-modification lands in quarantine/approval — never direct.

## 7. The Hermes strategy — integrate, then exceed

Reference research: [2026-06-07-hermes-agent.md](docs/research/2026-06-07-hermes-agent.md) ·
[2026-07-06-hermes-agent-migration-plan.md](docs/research/2026-07-06-hermes-agent-migration-plan.md)
(APPROVED) · the 2026-07-11 session archive.

**Verdict.** Hermes Agent is ahead on execution maturity: the closed skill-creation loop, a mature
multi-provider browser stack, portable terminal backends, gateway polish. Jarvis is ahead on
governance (Action Kernel, contracts, taint, tamper-evident audit), the personal-world ontology,
physical/multimedia presence, and local-first as a non-negotiable. Hermes is an excellent
*execution engine and learning subsystem*; it is not a house brain.

**Strategy.** Do **not** rebuild Hermes feature-by-feature. Adopt its mechanisms under Jarvis
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
| S8 | Time-to-first-governed-action | fresh install → first accepted autonomous action < 30 min | command-center funnel (0.19) |

## 8. Development order

Phases from the owner session, mapped to horizons and minors. **The proof track (0.12–0.20, ⭐B0,
72h soak, design partners) runs in parallel from day 1 and is not displaced** — it is the other
half of the 1.0 gate (§9). Capability horizons unpark their frozen modules per the revised
park-list policy (BACKLOG → ORIZONT 26 Phase 6).

| Phase | Horizon | Version | Builds on (don't rebuild) |
|---|---|---|---|
| 1 | **O27 Capability Registry & Unified Action API** | v0.21.0 | O24 V2 registry, `automation_contracts.py`, action-auth matrix, `agent_runtime.py` |
| 2a | **O28 Computer & Browser Operator** | v0.22.0 | H15 governed stubs, `core/environments/`, ToolRPC |
| 2b | **O29 Multimedia Director** | v0.23.0 | `spotify_plugin.py`, `media_catalog.py`, interrupt budgets |
| 3 | **O30 House Brain** | v0.24.0 | homebridge/iot plugins, Wyoming, bi-temporal KG |
| 4 | **O31 Camera Intelligence** | v0.25.0 | greenfield; `llm/vlm.py` for description; privacy contract first |
| 5 | **O32 Capability Acquisition** | v0.26.0 | O20 learning loop, skill lifecycle, sandbox, `grounded_plan.py` |
| 6 | **O33 Ambient Intelligence** | v0.27.0 | `autonomy/observer.py`, watchers, policy, night-shift |

Order can adapt to reality (a design partner's need may pull O29 before O28); **gates cannot be
skipped** (MOONSHOT §4).

## 9. What this changes about v1.0

**Decision (owner, 2026-07-11):** the 1.0 gate expands. The "v3.0 vision" is pulled **into** 1.0 —
explicitly, so there is no ambiguity about scope.

> **1.0 = (a) the proof track complete AND (b) all six pillars at their v1 bar.**

**(a) Proof track — unchanged:** the H23 spine + O24–O26 program; ⭐B0 governed-autonomy manual
run; 72h unattended soak; 1–3 design partners running a non-owner install ≥2 weeks with real
north-star data; owner legal/brand (license flip, GitHub settings); manual-test/audit pass tags
the version.

**(b) The v1 bar per pillar:**

| Pillar | v1 bar (VERIFIED via the reality harness, not asserted) |
|---|---|
| P1 Perception | camera events + house sensor state flowing into memory with retention/consent controls |
| P2 Communication | presence-aware delivery on ≥2 output surfaces beyond chat (e.g. speaker + display) |
| P3 Action | real browser + desktop operator behind the kernel; the API→CLI→UI→visual router picks the lowest-risk path |
| P4 House | HA state + device/room/occupant graph + governed actuation (locks/doors never below strong confirmation) |
| P5 Media | `present()` on ≥2 device classes with session etiquette |
| P6 Evolution | one full acquisition loop (gap → research → generate → sandbox → approve → registry → reuse) demonstrated under approval |

**Post-1.0 staging keeps its meaning:** v1.x = deepen the pillars + the hosted-Pro decision;
v2.0-class = multi-user/households, moderated marketplace, ecosystem (MOONSHOT §4 Phase 3,
unchanged). The owner accepts that the expanded gate moves 1.0 out by roughly a year.

## 10. Risks and honest constraints

- **Scope-gravity is the #1 risk** (the year-one review's warning stands). Mitigation: the phase
  gates above; the proof track runs first and in parallel; the park-list guard (H23.28) gets
  implemented, not just described; one horizon in flight at a time.
- **Actuation needs the owner's hardware.** Browser/desktop drivers, HA, cameras, media devices
  are host seams — engineering can build the governed rails and hermetic harnesses; only the box
  proves them live.
- **Cameras are privacy-critical.** H31.6 (frames never leave the box; household consent;
  kill-switch coverage; retention defaults) precedes any frame processing — it is deliberately
  the first item of ORIZONT 31.
- **The north-star + counter-metrics stay the drift guard** (MOONSHOT §6 unchanged): if interrupt
  rate, reject rate, %-local or p95 degrade while capabilities grow, the program is failing even
  if features ship.

## 11. Doc relationships

| Question | Doc |
|---|---|
| Why we exist, principles, phase gates | [MOONSHOT.md](MOONSHOT.md) |
| What can Jarvis do / what's missing / the Hermes bar | **this file** |
| What to build next, prioritized | [BACKLOG.md](BACKLOG.md) (wins on priorities) |
| Where the strategy came from | [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md) (immutable) |
| What only the owner can do | [docs/OWNER_TASKS.md](docs/OWNER_TASKS.md) |
