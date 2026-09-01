# Nerva — The Personal Intelligence Operating System (product & capability vision)

> Generated: 2026-07-11 · Merged: 2026-07-12 (this document unifies the two parallel vision drafts —
> #661 `docs/NERVA_VISION.md` and #662 `AI_OS_VISION.md` — per the owner's reconciliation decisions;
> the superseded draft is now a pointer stub at [docs/NERVA_VISION.md](docs/NERVA_VISION.md)) ·
> **Owner-approved** · Downstream of [MOONSHOT.md](MOONSHOT.md) §1/§5; upstream of
> [BACKLOG.md](BACKLOG.md) ORIZONT 27–33. When this doc and BACKLOG disagree on priorities,
> **BACKLOG wins** — fix the stale one. Provenance (the full owner session, immutable):
> [docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md](docs/research/2026-07-11-ai-os-vision-and-hermes-strategy.md).
>
> **Naming:** **Nerva** is the end-user product brand (published by **Digitaholic**). The
> in-product rename was executed 2026-07-19 (HUD, executable + `Documents/Nerva`, landing, README,
> logo — the orchestrator *agent* keeps its Jarvis persona per §2). `jarvis-hub` remains the
> repository/package codename until the GitHub repo rename (owner task —
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
| **Decide** | orchestrator + 18 specialist agents, autonomy policy, `agent_runtime.py` model-directed loop (H20.R1) |
| **Act** | the **Action Kernel** (O24 — Gate-K, 21 action kinds mediated), brokers, ToolRPC, sandbox |
| **Verify** | the **Verification Fabric** (O24 — reality harness, SEAM→WIRED→VERIFIED→GA registry; in-process — resets each boot, a durable committed snapshot is V3, pending) |
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
└── Execution topology — local, Docker, SSH*, edge and optional cloud targets
```

\* SSH is profile/policy inventory only today — no transport exists in-repo (see §3).

Atlas provides the shared state against which Cortex reasons. **Vision observes. Atlas locates and
contextualizes. Cortex decides. Synapse supplies the capability. Ultron authorizes. Nerva executes
and verifies.**

## 3. Honest baseline (2026-08-09)

- **v0.11.0**, feature-complete + refactored; test/route counts are auto-synced in
  [STATUS.md](STATUS.md) (never trust hand-written numbers elsewhere).
- **Ultron / Gate-K**: every one of the 21 registered privileged action kinds crosses
  `kernel.authorize` (action-auth snapshot has zero `pending`; the matrix cannot see a kind that
  was never registered).
- **Synapse seeds — ORIZONT 20 (Hermes Mining) 6/6 + live wave**: the governed per-turn learning
  loop is merged (default-off — and still off in the Design-Partner posture, which omits
  `cognition.review_enabled`), skill lifecycle + curator live, ToolRPC spine + execution
  environments (local/docker) merged (no SSH transport exists).
- **H15 computer-use**: governance complete (egress allowlist, approval queue, injection defense,
  a11y fusion) and the real drivers are now in-repo as **owner-enabled opt-in host seams** — the
  Playwright browser driver (`browser_playwright.py`) + Windows desktop driver (`desktop_host.py`,
  O28, #673); hermetic CI proves the rail, but live owner-hardware validation is owner-gated and
  not claimed by CI.
- **Media**: Spotify control is real; the O29 Media Director (`media_director.py`, #669/#674) now
  delivers the `media_player` abstraction + device registry + kernel-mediated `present()`
  (`media.present`/`media.restore`); real Chromecast/Spotify-Connect actuation remains an
  owner-wired host seam — `NullMediaDriver` refuses honestly by default.
- **House (Atlas)**: the O30 House Brain (#675) delivers the read-first Home Assistant
  REST/WebSocket state adapter (`house/home_assistant.py`), the device/room/occupant graph
  (`house/graph.py` + the encrypted `house/private_store.py` for occupant/presence) and governed
  actuation; presence inference now has a default-off production writer (`house/ingest.py`,
  `house.presence_enabled`) feeding HA person/device_tracker + room motion into it on each
  state read — room presence is claimed only when identity and same-room motion corroborate,
  and the route's `presence_status` field reports off/live/degraded separately from the
  array. Homebridge + Tuya + Wyoming voice
  satellite also exist. WorldView + Signal Layer are substantial but not yet unified with
  house/device/execution state.
- **Cameras (Vision)**: H31 (#676) delivers read-only, LAN-pinned Frigate metadata +
  discovery-only ONVIF behind versioned consent and mandatory privacy masks
  (`agents/core/cameras/`); direct RTSP ingest is not shipped (no decoder/stream surface).
  Both camera seams are owner-side by design and now say so at runtime: ONVIF discovery
  needs the manually installed `wsdiscovery` package (deliberately unlocked, like the
  Playwright/pywinauto hosts; a stock install answers `onvif_dependency_missing` with the
  install remedy in `detail` — `cameras/onvif.py`), and the VLM description leg needs a
  self-hosted OpenAI-vision server — LM Studio is first-class via `JARVIS_VLM_BACKEND=lmstudio`
  (`llm/vlm.py::resolve_vlm_config`; the consent-scoped `camera.vlm_*` loopback path is
  unchanged, default-off).
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
  `/api/vlm/describe` — client only; needs an owner-hosted OpenAI-vision server via
  `JARVIS_VLM_URL`), screen grounding (`screen_grounding.py`), opt-in passive capture,
  7-phase ingestion pipeline, host observer (`autonomy/observer.py`), channel inbounds;
  read-only camera perception (H31 — Frigate metadata + discovery-only ONVIF) and house
  sensor state/presence (H30 — HA adapter + presence inference, fed by the default-off
  `house/ingest.py` production writer since GAP-9 — see §3).
- **Missing:** direct RTSP/camera stream intelligence (H31 is read-only metadata + discovery,
  with no Jarvis decoder/stream surface); vehicle telemetry; desktop observation as a routine
  perception source; ambient correlation depth beyond the delivered H33 monitors.
- **Closed by:** ORIZONT 31 (delivered — wave-1 read-only perception; RTSP ingest stays a
  post-1.0 seam), ORIZONT 30 (delivered — house sensors/presence), ORIZONT 33 (delivered —
  ambient monitors); vehicle/desktop perception ride the post-1.0 depth lanes.

### P2 — Communication (~70–80%) — the Nerva experience

*Interact naturally everywhere; conversation continuity across channels and devices; know who is
speaking, where, and how private the context is; deliver on the right surface (speaker, display,
phone, headphones) for the person, room, privacy and urgency.*

- **Exists:** web SSE, voice, Telegram, Discord, email, Slack; `channels/session.py` +
  `gateway.py`; channel inbox transport v0; interrupt budgets (≤4 push/day); Wyoming satellite
  protocol for room voice endpoints.
- **Missing:** presence-aware delivery as a finished policy (H34.2 owner-presence and H30.6
  room-aware voice ship the rails, not the full delivery ladder); ambient vs private delivery
  decisions at scale. **Personality
  and humour as social policy** — contextual humour with callbacks, household-safe modes,
  user-specific tone and timing, no repetitive or forced jokes, the ability to shift between
  concise operational mode and richer conversational mode (a persistent companion, not a command
  shell — and not a standalone joke generator).
- **Closed by:** ORIZONT 29 (delivered — `present()` output routing), ORIZONT 30 (delivered —
  room context), ORIZONT 33 (delivered — ambient ladder); personality depth rides the existing
  cognition/persona lane (O21, delivered).

### P3 — Action (~45%) — Synapse + Ultron

*Actually perform work, on the hierarchy* **API → CLI/script → structured browser/accessibility
automation → visual mouse/keyboard fallback** *(visual is the fallback, never the default), with
post-action verification and rollback where possible.*

- **Exists:** the Action Kernel (O24) with contracts (`automation_contracts.py`), budgets,
  kill-switch, audit chain; write-back + connector builders (12 cataloged SaaS actions in
  `writeback.py` + `writeback_connectors.py`); ToolRPC
  (`tool_rpc.py`) + the model-directed tool loop (`agent_runtime.py`, default-off); execution
  environments local/docker (the execution-target layer executes **docker** through
  `GovernedTargetRunner`, which authorizes against the policy plane first — #980; `local` and
  `ssh` still refuse honestly, and no SSH transport exists);
  sandbox with output caps; the unified Action API (O27 — `perform(capability, params)` + the
  Capability Registry); the action-hierarchy router + Playwright/Windows desktop drivers as
  owner-gated host seams (O28).
- **Missing:** live owner-hardware proof of the O28 browser/desktop drivers (hermetic CI is
  green; real Windows UIA + installed-Playwright validation is owner-gated and unclaimed);
  cross-surface breadth beyond the O28 first slice (the action hierarchy exists as a router but
  the full API→CLI→UI→visual surface breadth still lands with real operators).
- **Closed by:** ORIZONT 27 (delivered — unified Action API), ORIZONT 28 (delivered — real
  operators; owner hardware validation pending).

### P4 — Environment / House Brain (~20%) — Atlas

*The operating system for the house: properties, floors, rooms, zones, occupants, guests and
permissions; sensors, cameras, displays, speakers and actuators; routines, presence and temporal
patterns; climate, lighting, energy, security and media; household privacy and interruption
policies.*

- **Exists:** the O30 House Brain (`agents/core/house/` — read-first Home Assistant REST/WebSocket
  state adapter `home_assistant.py`, device/room/occupant topology `graph.py`, encrypted private
  occupant/presence store, presence inference with its default-off production writer
  (`house/ingest.py`, GAP-9), governed actuation through the Action Kernel);
  `plugins/homebridge.py` (HomeKit accessories, LOCAL_ONLY), `plugins/iot_control.py`
  (Tuya, partly mock), `voice/wyoming.py` (HA Voice PE satellites); the bi-temporal KG as the
  house graph's home; WorldView/Signal Layer as Atlas's external-world half.
- **Missing:** household policies (privacy zones, per-person authority); the last open O30 item —
  the ambient light bridge (H30.8); live owner-hardware HA integration
  (the H30 reality pack is hermetic; the live read probe is double opt-in — the GAP-9
  presence writer ships hermetically tested but unproven on the owner's real HA box).
- **Closed by:** ORIZONT 30 (delivered — H30.1–H30.7; H30.8 ambient light bridge still open).
  Home Assistant/Homebridge provide device abstraction, but **Nerva
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
  generated-media catalog/exports (`media_catalog.py`, `media_gen.py`); the O29 Media Director
  (`media_director.py`) — `media_player` abstraction + device registry, kernel-mediated
  `present()` (`media.present`/`media.restore`), content resolvers and session etiquette.
- **Missing:** real Chromecast/Spotify-Connect/AirPlay actuation (drivers are owner-wired host
  seams — `NullMediaDriver` refuses honestly by default; AirPlay is not a registered device kind);
  cross-room media movement.
- **Closed by:** ORIZONT 29 (delivered — wave 1; real driver actuation + cross-room movement are
  owner-wired host seams / post-1.0).

### P6 — Capability Evolution (~10%) — Synapse

*Instead of "I can't" → "I don't know **yet**": understand the intended outcome → search the
Capability Registry → inspect available tools, APIs, devices and documentation → produce a bounded
implementation plan → generate a temporary skill or adapter → test it in isolation → verify
read-only behavior first → request approval according to risk → execute and verify the real
outcome → promote the validated capability for reuse.*

- **Exists:** the O32 acquisition loop (gap detection → reuse-first search → governed research →
  strict-local generate + sandbox-test → permanent owner approval + Action Kernel mediation →
  signing → registry → rollback; H32.1–H32.7); the full skill lifecycle (loader, importer, usage
  telemetry, nightly curator, proposals, signing, marketplace with rollback); `self_evolution.py`
  (governed prompt optimization); the per-turn learning loop (O20.L — facts + skill patches
  distilled under governance); sandbox + quarantine.
- **Missing:** real-world acquisition at scale (the hermetic O32 loop is proven; generated
  capabilities still need sandboxed live execution and owner-hardware breadth). Generated
  capabilities never bypass Synapse validation or Ultron governance.
- **Closed by:** ORIZONT 32 (delivered — the loop) + ORIZONT 27 (delivered — the registry it
  feeds).

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
memory fusion + bi-temporal KG + cognition layer + the 18 specialists + autonomy stack (exists;
house state = O30, delivered; WorldView/Signal Layer fold in as Atlas's external half). **Ultron** =
O24 (exists; the boundary). **Synapse execution plane** = O20/H20 ToolRPC + environments + skills +
subagents (exists; operators = O28, delivered — owner hardware validation pending).
**Physical Adapters** = O29/O30/O31 (delivered; real driver actuation stays owner-gated).

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
| verification state | V2 `observability/capability_registry.py` — `CapabilityRecord` + SEAM→WIRED→VERIFIED→GA (only the V1 reality harness promotes to VERIFIED; the record set is in-process and resets each boot) |
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
(Atlas), physical/multimedia presence, and local-first as a non-negotiable. The moat, stated where
it survives contact: **Hermes has HA as a tool; Nerva has a house model** — Hermes's Home Assistant
support is an `area` name filter over its entities plus per-family-member profile isolation, not a
model of the house — and **Hermes declined to build an action-level audit chain; we built one and
have not turned it on.** Honest counterweight: Hermes gates less than its approval story implies —
`ha_call_service` has no approval, container isolation *replaces* command checks, smart approvals
auto-approve low risk, and memory writes default to no approval. **Hermes-derived components are
hands and procedural learning. Nerva remains the brain, identity, policy layer and house operating
model.**

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

<!-- GAP-8 re-baseline evidence (2026-08-09):
What changed (all in this doc; no other file touched) and the evidence for each:

1. §1 table + §3 Gate-K bullet: action-kind count 18 → 20 → 21. Evidence: the 21 KERNEL entries in
   `agents/core/kernel/registry.py` ACTION_REGISTRY (lines 32–100) == the 21 keys of
   `tests/_snapshots/action_auth.json` (zero `pending`); the count was 18 before #746
   (f2cfe7f4) registered `channel.reply` + `skill.install`, then #908 (b7df10dd) registered
   `host.control` (the 21st). The "11"/"12" figures are
   historical (pre-#746); the §6 registry-field table already points at the snapshot as truth.
2. §3 H15 bullet: "actuation is stubbed … no real Playwright/VM driver in-repo" → real drivers
   now exist as owner-gated host seams. Evidence: `agents/core/browser_playwright.py:39`
   (`PlaywrightBrowserDriver`), `agents/core/desktop_host.py` (Windows desktop driver),
   BACKLOG.md H28.1/H28.4 (delivered 2026-07-12, #673).
3. §3 Media bullet: "no Chromecast / media_player abstraction" → O29 delivered it. Evidence:
   `agents/core/media_director.py` (DeviceRegistry/MediaDirector/present, #669/#674),
   BACKLOG.md H29.1–H29.6 (19/19 SP complete); real driver actuation stays an owner-wired
   host seam (`NullMediaDriver` default).
4. §3 House bullet: "no Home Assistant state API integration and no room/occupant/device graph"
   → delivered. Evidence: `agents/core/house/home_assistant.py` (H30.1 read-first HA
   REST/WebSocket adapter), `house/graph.py` (H30.2 topology), `house/private_store.py` +
   `house/presence.py` (H30.3), BACKLOG.md H30.1–H30.7 (29/29 SP, #675).
5. §3 Cameras bullet: "nothing exists (no RTSP/ONVIF/Frigate code anywhere)" → H31 delivered
   read-only Frigate + discovery-only ONVIF; direct RTSP ingest still absent. Evidence:
   `agents/core/cameras/` (frigate.py, onvif.py, privacy.py, vault.py, vlm.py), BACKLOG.md
   H31.1–H31.6 (#676); `rg -n "RTSP|rtsp://" agents/core/cameras/` → 0 hits.
6. §3 header date: baseline re-dated 2026-07-11 → 2026-08-09 (the re-baseline date). §4's
   "(owner-session estimates 2026-07-11)" note is untouched — the percentages still originate
   from that session and are correct (P1 ~35%, P2 ~70–80%, P3 ~45%, P4 ~20%, P5 ~15%,
   P6 ~10%; no pillar 0% or unstated) → no §4 percentage change was needed.
7. §4 P1 Exists/Missing/Closed-by: cameras + house sensor streams + ambient now delivered.
   Evidence: H31 (#676) and H30 (#675) and H33.1–H33.6 (BACKLOG.md) all ✅; RTSP/vehicle/
   desktop remain open.
8. §4 P2 Missing/Closed-by: "speaker/room identity" + "media surfaces" removed (delivered via
   H30.6 room-aware voice and O29 present()); presence ladder + ambient delivery kept as open;
   O21 persona lane delivered. Evidence: BACKLOG.md H30.6, H29.x, ORIZONT 21 10/10 ✅ (line 2569).
9. §4 P3 Exists/Missing/Closed-by: "local/docker/ssh" → "local/docker (SSH is policy-plane
   inventory only — no transport)" per the accepted GAP-9/#855 finding; "~27 SaaS actions" →
   12 cataloged (`writeback.py` 5 + `writeback_connectors.py` 7 `_reg` entries); unified Action
   API + hierarchy router + real drivers delivered (O27/O28, H27.3/H28.2/H28.1/H28.4);
   owner-hardware validation remains open. Evidence: `agents/core/environments/targets.py:3`
   ("never launches a subprocess, container, or SSH session") and :343 ("host/SSH transports
   remain disabled by default"), BACKLOG.md O27/O28 items.
10. §4 P4 Exists/Missing/Closed-by: HA state integration / device-room-occupant graph / presence
    removed from Missing (delivered, H30.1–H30.3); household policies + H30.8 ambient light
    bridge + live owner-hardware HA remain open. Evidence: BACKLOG.md H30.1–H30.8.
11. §4 P5 Exists/Missing/Closed-by: media_player abstraction + device registry + present() +
    resolvers + etiquette delivered (H29.1–H29.4); real driver actuation (host seam) + AirPlay
    (not a registered kind: chromecast/spotify_connect/browser_tab/local/speaker/tv) +
    cross-room movement remain open. Evidence: BACKLOG.md H29.1–H29.4, media_director.py kinds.
12. §4 P6 Exists/Missing/Closed-by: the closed acquisition loop is delivered (H32.1–H32.7);
    live acquisition at scale remains open. Evidence: BACKLOG.md H32.1–H32.7 ✅.
13. Unchanged after verification: v0.11.0 + 17 specialists (STATUS.md current-version line),
    O20 6/6 (BACKLOG.md ORIZONT 20 6/6 ✅), the proof track still pending (BACKLOG.md A1/A2/A7 ⬜).
14. §5 layer-mapping parentheticals: "house state is new, O30 / operators land in O28 / O29·O30·O31
    (mostly new)" → delivered markers, same evidence as items 2–5 (O28 #673, O29 #669/#674,
    O30 #675, O31 #676); owner-gated hardware validation explicitly left pending.
15. GAP-8 re-verification (2026-08-23 wave): §4 percentages re-checked unchanged and correct
    (P1 ~35%, P2 ~70–80%, P3 ~45%, P4 ~20%, P5 ~15%, P6 ~10%; no pillar 0%); the
    privileged-action-kind figure stands at 21 — re-counted in this worktree: 21
    `Mediation.KERNEL` entries (`agents/core/kernel/registry.py:34–99`) == 21 snapshot keys,
    all `kernel` (BACKLOG's "snapshot now covers 18" was itself stale). Item 1 above updated
    to match (20 → 21, registry lines 32–100).
16. GAP-9 honesty hedges (2026-08-23 wave; each verified in this worktree before editing):
    presence predicates have no production writer — the store writers
    `house/private_store.py:435/:445` are reached only via `PresenceInference.infer`
    (`house/presence.py`), whose only non-test caller is the H30 probe
    (`observability/house_reality.py:514`), so `/api/house/state.presence` serves `[]`
    (`routers/house.py:333/:355/:370`); ONVIF discovery imports the undeclared `wsdiscovery`
    package lazily (`cameras/onvif.py:331`; zero declarations in requirements*.txt /
    pyproject.toml); the camera VLM leg is a default-off client for an owner-hosted
    OpenAI-vision server (`cameras/runtime.py:364–376`, `llm/vlm.py:10–12/:28`); the
    execution-target layer executes docker only, via `GovernedTargetRunner`
    (`environments/execution.py:32–33`, constructed in production at
    `autonomy_coordinator.py:461–465`) — #980 closed the "never executes" half of this claim;
    `local`/`ssh` return explicit not-implemented refusals and there is still no
    paramiko/asyncssh anywhere, so the no-SSH-transport half stands;
    reality-harness promotion is in-process and boot-ephemeral
    (`observability/capability_registry.py:55/:68`, `reality_harness.py:19–23`;
    `.github/workflows/reality.yml` uploads no artifact); README's voice engines ship in no
    install path (`requirements.txt:33–35` commented out, `requirements-beta.txt:46–54` hint
    comments only; all three install scripts install only `-r requirements-beta.txt`). §8's
    Hermes restatement was verified already-applied at base — no edit needed there; the
    Hermes-side facts are corroborated by
    `docs/research/2026-07-25-nerva-vs-hermes-honest-gap-analysis.md` (not by Hermes source).
17. GAP-9 functional closure (2026-08-29 wave): all five item-16 gaps were built rather than
    re-hedged — presence gained the default-off production writer `house/ingest.py`
    (HA snapshot -> PresenceInference, `house.presence_enabled`, `presence_status` route
    field); ONVIF's missing dependency now names its remedy at runtime
    (`onvif_dependency_missing` + detail, Playwright-style deliberately-unlocked);
    the VLM leg gained first-class local backend selection
    (`llm/vlm.py::resolve_vlm_config`, LM Studio on 1234/v1, honest refusal reasons);
    the execution-target layer gained its transport (`environments/execution.py`,
    docker-only, audit-before-spawn, behind the gated `terminal_run` tool +
    `JARVIS_TERMINAL_TARGETS`); and reality runs persist as evidence
    (`observability/reality_evidence.py` + reality.yml artifact upload,
    promotion still in-process-only per V3). Prose above updated in the same wave.
--> 
